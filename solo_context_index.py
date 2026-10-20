"""Private, on-demand full-text source index for Solo workspaces.

No model downloads, background watchers, network access or code execution.
The index is local; only explicitly requested search excerpts leave the host.
"""
import hashlib
import os
from pathlib import Path
import re
import sqlite3

EXTENSIONS = frozenset({
    ".py", ".pyi", ".c", ".cc", ".cpp", ".h", ".hpp", ".rs", ".go",
    ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".css", ".qss",
    ".html", ".md", ".sh", ".sql",
})
SPECIAL_NAMES = frozenset({"Makefile", "CMakeLists.txt", "Dockerfile"})
EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    "dist", "build", "target", "coverage", ".next", ".cache", "vendor",
    "site-packages", "tmp",
})
SENSITIVE_PARTS = ("secret", "credential", "password", "private_key", "access_token")
MAX_FILES = 1600
MAX_FILE_BYTES = 96_000
MAX_TOTAL_BYTES = 16_000_000
MAX_WALK_ENTRIES = 8000
CHUNK_LINES = 48
CHUNK_OVERLAP = 8
MAX_MATCHES = 12
# Best effort: cannot guarantee that arbitrary source files contain no secrets.
REDACT = re.compile(
    r"(?im)(\b(?:api[_-]?key|access[_-]?token|password|secret)\b\s*[:=]\s*)"
    r"(['\"]?)[^\s'\";,}]{8,}\2"
)


def _allowed(name):
    lower = name.lower()
    return (
        not name.startswith(".")
        and not any(word in lower for word in SENSITIVE_PARTS)
        and (Path(name).suffix.lower() in EXTENSIONS or name in SPECIAL_NAMES)
        and not name.endswith((".min.js", ".map"))
    )


def _index_path(workspace, root):
    state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    folder = state / "solo-mcp" / "context-indexes"
    # Never let a symlink redirect the private database out of its intended folder.
    for part in (state / "solo-mcp", folder):
        if part.is_symlink():
            raise ValueError("Diretório de índice simbólico bloqueado")
        part.mkdir(parents=True, exist_ok=True, mode=0o700)
        part.chmod(0o700)
    token = hashlib.sha256((workspace + "\0" + str(root)).encode("utf-8")).hexdigest()[:24]
    path = folder / (token + ".sqlite3")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Banco de índice inválido")
    return path


def _walk(root):
    """Sorted bounded walk; no hidden directories or directory symlinks."""
    visited = 0
    for folder, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = sorted(
            name for name in dirs
            if not name.startswith(".")
            and name.lower() not in EXCLUDED_DIRS
            and not name.lower().startswith(("build-", "cmake-build-"))
            and not any(s in name.lower() for s in SENSITIVE_PARTS)
            and not (Path(folder) / name).is_symlink()
        )
        for name in sorted(files):
            visited += 1
            if visited > MAX_WALK_ENTRIES:
                yield None
                return
            if _allowed(name):
                path = Path(folder) / name
                if not path.is_symlink() and path.is_file():
                    yield path


def _chunks(text):
    lines = text.splitlines()
    for start in range(0, len(lines), CHUNK_LINES - CHUNK_OVERLAP):
        part = lines[start:start + CHUNK_LINES]
        if part:
            yield start + 1, start + len(part), "\n".join(part)[:6000]


def _terms(query):
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 200:
        raise ValueError("Consulta deve conter de 2 a 200 caracteres")
    parts = [part for part in re.findall(r"\w{2,40}", query, re.UNICODE) if part.strip("_")]
    if not parts:
        raise ValueError("Consulta não contém termos pesquisáveis")
    # Quote each token instead of accepting FTS5 operators or syntax from Issues.
    return " OR ".join('"' + term.replace("_", " ") + '"' for term in parts[:10])


def search(root, workspace, query, limit=8):
    expression = _terms(query)
    if type(limit) is not int or not 1 <= limit <= MAX_MATCHES:
        raise ValueError("Limite de resultados deve estar entre 1 e 12")
    root = Path(root).resolve(strict=True)
    index_path = _index_path(workspace, root)
    db = sqlite3.connect(str(index_path), timeout=10)
    os.chmod(index_path, 0o600)
    try:
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("CREATE TABLE IF NOT EXISTS tracked (path TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL)")
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(path UNINDEXED, start_line UNINDEXED, end_line UNINDEXED, body, tokenize='unicode61')")
        known = {path: (mtime, size) for path, mtime, size in db.execute("SELECT path,mtime_ns,size FROM tracked")}
        seen = set()
        updated = 0
        scanned_bytes = 0
        truncated = False
        for path in _walk(root):
            if path is None:
                truncated = True
                break
            relative = str(path.relative_to(root))
            if len(seen) >= MAX_FILES:
                truncated = True
                break
            try:
                stat = path.stat()
                if not path.resolve(strict=True).is_relative_to(root) or stat.st_size > MAX_FILE_BYTES:
                    continue
                if scanned_bytes + stat.st_size > MAX_TOTAL_BYTES:
                    truncated = True
                    break
                scanned_bytes += stat.st_size
                seen.add(relative)
                signature = (stat.st_mtime_ns, stat.st_size)
                if known.get(relative) == signature:
                    continue
                raw = path.read_bytes()
                if b"\x00" in raw[:4096]:
                    continue
                text = raw.decode("utf-8")
                text = REDACT.sub(r"\1[REDACTED]", text)
            except (OSError, UnicodeError, ValueError):
                # Do not return an old cached excerpt if a file became unreadable.
                db.execute("DELETE FROM chunks WHERE path=?", (relative,))
                db.execute("DELETE FROM tracked WHERE path=?", (relative,))
                continue
            db.execute("DELETE FROM chunks WHERE path=?", (relative,))
            for start, end, content in _chunks(text):
                db.execute(
                    "INSERT INTO chunks(path,start_line,end_line,body) VALUES (?,?,?,?)",
                    (relative, start, end, content)
                )
            db.execute(
                "INSERT OR REPLACE INTO tracked(path,mtime_ns,size) VALUES (?,?,?)",
                (relative, *signature)
            )
            updated += 1
        # If a scan was truncated, preserve entries not reached this time.
        if not truncated:
            for obsolete in known.keys() - seen:
                db.execute("DELETE FROM chunks WHERE path=?", (obsolete,))
                db.execute("DELETE FROM tracked WHERE path=?", (obsolete,))
        db.commit()
        rows = db.execute(
            "SELECT path,start_line,end_line,snippet(chunks,3,'[',']','…',24) "
            "FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks) LIMIT ?",
            (expression, limit)
        ).fetchall()
        matches = [
            {"path": path, "line_start": int(start), "line_end": int(end),
             "excerpt": excerpt[:850]}
            for path, start, end, excerpt in rows
        ]
        return {
            "workspace": workspace, "query": query, "matches": matches,
            "files_indexed": db.execute("SELECT COUNT(*) FROM tracked").fetchone()[0],
            "files_updated": updated, "scan_truncated": truncated,
            "note": "Índice local. Apenas trechos correspondentes enviados à Issue privada; "
                    "arquivos ignorados e mudanças externas podem não aparecer."
        }
    finally:
        db.close()
