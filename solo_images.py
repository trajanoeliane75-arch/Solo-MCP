"""Private GitHub Issues transport for approved diagnostic JPEGs.

Each screenshot is split into numbered JSON comments on the SAME private task
Issue. The result metadata includes SHA256 so readers can verify reconstruction.
Do not call this from a public repository.
"""
import base64
import hashlib
import json

IMAGE_MARKER = "SOLO_MCP_IMAGE_V1"
CHUNK_CHARS = 20000
MAX_IMAGE_BYTES = 420_000


def make_chunks(result):
    if not isinstance(result, dict):
        raise ValueError("Resultado inválido")
    if result.get("ok") is not True:
        return result, []
    original = result.get("result")
    if not isinstance(original, dict) or "_image_b64" not in original:
        return result, []
    encoded = original["_image_b64"]
    if not isinstance(encoded, str) or len(encoded) > (MAX_IMAGE_BYTES * 4 // 3 + 8):
        raise ValueError("Imagem inválida ou maior que o limite")
    try:
        image = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("Captura com base64 inválido") from exc
    if not image.startswith(b"\xff\xd8\xff") or not 0 < len(image) <= MAX_IMAGE_BYTES:
        raise ValueError("Captura não é JPEG válido ou excede 420 KB")
    sha = hashlib.sha256(image).hexdigest()
    data = base64.b64encode(image).decode("ascii")
    pieces = [data[i:i+CHUNK_CHARS] for i in range(0, len(data), CHUNK_CHARS)]
    if len(pieces) > 32:
        raise ValueError("Imagem exigiria muitos comentários")
    output = []
    for i, piece in enumerate(pieces):
        output.append(
            IMAGE_MARKER + "\n" + json.dumps(
                {"index": i, "total": len(pieces), "sha256": sha,
                 "mime": "image/jpeg", "data": piece}, separators=(",", ":")
            )
        )
    safe = {key: value for key, value in original.items() if key != "_image_b64"}
    safe["image"] = {"mime": "image/jpeg", "sha256": sha,
                     "bytes": len(image), "parts": len(pieces),
                     "transport": "github-private-issue-comments"}
    return {**result, "result": safe}, output


def restore_comments(comments, expected_sha):
    """For a trusted consumer of private Issue comments, never JSON instructions."""
    pieces = {}
    total = None
    for comment in comments:
        body = comment.get("body", "")
        if not isinstance(body, str) or not body.startswith(IMAGE_MARKER + "\n"):
            continue
        try:
            chunk = json.loads(body.split("\n", 1)[1])
        except (ValueError, TypeError, IndexError):
            continue
        if not isinstance(chunk, dict) or chunk.get("sha256") != expected_sha:
            continue
        idx, count, data = chunk.get("index"), chunk.get("total"), chunk.get("data")
        if (type(idx) is not int or type(count) is not int
                or not 0 <= idx < count <= 32 or not isinstance(data, str)
                or len(data) > CHUNK_CHARS):
            continue
        if total is None:
            total = count
        if count != total:
            continue
        pieces[idx] = data
    if total is None or len(pieces) != total:
        raise ValueError("Captura incompleta: faltam comentários da imagem")
    image = base64.b64decode("".join(pieces[i] for i in range(total)), validate=True)
    if hashlib.sha256(image).hexdigest() != expected_sha:
        raise ValueError("Imagem reconstruída não passou na verificação SHA-256")
    if not image.startswith(b"\xff\xd8\xff") or len(image) > MAX_IMAGE_BYTES:
        raise ValueError("Imagem reconstruída inválida")
    return image
