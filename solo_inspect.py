"""On-demand visual diagnostics for a web page or a selected Linux X11 window.

A screenshot is sensitive data. Only call from the approval-gated inspect_screen
action, and return bytes in memory for the private control-channel transport.
No continuous recording, background screenshot or automatic Chrome attachment.
"""
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

MAX_SCREENSHOT_BYTES = 420_000
MAX_DOM_CHARS = 3500
MAX_CONSOLE_MESSAGES = 12
WINDOW_ID = re.compile(r"Window id:\s*(0x[0-9a-fA-F]+)\b")


def validate_target(task):
    mode = task.get("mode")
    if mode not in ("web", "window"):
        raise ValueError("Modo de inspeção: web ou window")
    if mode == "window":
        if task.get("url") is not None:
            raise ValueError("Inspeção de janela não aceita URL")
        return {"mode": "window"}
    url = task.get("url")
    if not isinstance(url, str) or not 1 <= len(url) <= 600 or any(
        ord(c) < 32 for c in url
    ):
        raise ValueError("URL inválida. Use http://127.0.0.1:PORTA ou localhost")
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or parsed.username is not None
                or parsed.password is not None or parsed.hostname not in
                ("localhost", "127.0.0.1", "::1")
                or parsed.fragment or parsed.port is None
                or not 1 <= parsed.port <= 65535):
            raise ValueError("A inspeção web inicial aceita apenas localhost HTTP com porta explícita")
    except ValueError as exc:
        raise ValueError("URL local inválida. Exemplo: http://127.0.0.1:3000/") from exc
    return {"mode": "web", "url": url}


def describe_target(task):
    target = validate_target(task)
    if target["mode"] == "window":
        return (
            "CAPTURA DE JANELA LINUX.\n"
            "Após autorizar, clique na janela que deseja compartilhar (cursor em cruz).\n"
            "A captura poderá conter dados particulares e será enviada em partes "
            "à Issue no repositório de CONTROLE PRIVADO do GitHub.\n"
            "NÃO selecione janelas com senhas, mensagens privadas ou dados sensíveis."
        )
    return (
        "INSPEÇÃO PLAYWRIGHT DE PÁGINA LOCAL:\n" + target["url"] + "\n"
        "Será aberta uma nova sessão Chromium, não a aba já aberta no Chrome.\n"
        "Enviaremos imagem, alguns erros do console e estrutura visível da página "
        "ao repositório de CONTROLE PRIVADO.\n"
        "Não conceda autorização se houver informações sensíveis na página."
    )


def make_image_result(image, mode, diagnostics=None):
    if not isinstance(image, bytes) or not image.startswith(b"\xff\xd8\xff"):
        raise RuntimeError("Captura JPEG inválida")
    if not 0 < len(image) <= MAX_SCREENSHOT_BYTES:
        raise RuntimeError(
            "Imagem grande demais para envio privado por Issues. "
            "Reduza o tamanho da janela ou da página e tente novamente."
        )
    return {
        "status": "captured",
        "mode": mode,
        "diagnostics": diagnostics or {},
        "_image_b64": base64.b64encode(image).decode("ascii"),
    }



import solo_kit

# Shared, app-owned kit: never install Playwright into a workspace or into
# the Python that runs the Solo-MCP approval panel.
INSPECT_VENV = solo_kit.KIT_ROOT


def sanitized_browser_env():
    return solo_kit.browser_env()


def inspect_web(url):
    """Run Playwright only in the dedicated Solo-MCP kit interpreter."""
    validate_target({"mode": "web", "url": url})
    worker_python = INSPECT_VENV / "bin" / "python"
    # sys.executable inside venv may be a symlink to the host interpreter.
    # sys.prefix identifies the active environment instead of that symlink.
    if Path(sys.prefix).resolve() != INSPECT_VENV.resolve():
        if not worker_python.is_file():
            raise RuntimeError(
                "Kit essencial não preparado. Abra Gerenciar > Ambiente e "
                "escolha Preparar / reparar kit para instalar Playwright e Chromium."
            )
        result = subprocess.run(
            [str(worker_python), str(Path(__file__).resolve()), "--web-worker", url],
            capture_output=True, text=True, timeout=50,
            env=sanitized_browser_env(), check=False
        )
        if result.returncode:
            raise RuntimeError(
                "Falha no kit de inspeção. Em Gerenciar > Ambiente, clique "
                "em Preparar / reparar kit."
            )
        try:
            parsed = json.loads(result.stdout)
            if not isinstance(parsed, dict) or parsed.get("mode") != "web":
                raise ValueError("Resposta inesperada do subprocesso")
            blob = base64.b64decode(parsed["_image_b64"], validate=True)
            return make_image_result(blob, "web", parsed.get("diagnostics"))
        except (KeyError, ValueError, TypeError, base64.binascii.Error) as error:
            raise RuntimeError("Resposta inválida do kit Playwright") from error

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright ausente no kit. Use Reparar kit.") from exc

    errors = []
    blocked = []
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True, env=sanitized_browser_env())
        except Exception as exc:
            raise RuntimeError(
                "Chromium do Playwright indisponível. Instale pelo ambiente Python "
                "do Solo-MCP com python -m playwright install chromium."
            ) from exc
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                device_scale_factor=1,
                accept_downloads=False,
                service_workers="block"
            )
            def route_request(route):
                requested = route.request.url
                try:
                    validate_target({"mode": "web", "url": requested})
                except ValueError:
                    if len(blocked) < MAX_CONSOLE_MESSAGES:
                        blocked.append("Recurso de endereço não local bloqueado")
                    route.abort()
                    return
                route.continue_()
            # Local-only by default; pages depending on external CDNs can render differently.
            context.route("**/*", route_request)
            page = context.new_page()
            def log_console(message):
                if message.type == "error" and len(errors) < MAX_CONSOLE_MESSAGES:
                    errors.append(message.text[:350])
            page.on("console", log_console)
            page.on("pageerror", lambda error: errors.append(str(error)[:350])
                    if len(errors) < MAX_CONSOLE_MESSAGES else None)
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=12000)
                page.wait_for_timeout(650)
                image = page.screenshot(
                    type="jpeg", quality=55, full_page=False,
                    animations="disabled", timeout=10000
                )
                title = page.title()[:180]
                status = response.status if response else None
                # Text can include app data; limit size; never read cookies/localStorage.
                dom = page.locator("body").inner_text(timeout=3000)[:MAX_DOM_CHARS]
            except Exception as exc:
                raise RuntimeError("Falha ao inspecionar página local: " + str(exc)[:220]) from exc
        finally:
            browser.close()
    return make_image_result(
        image, "web",
        {"title": title, "http_status": status,
         "body_text": dom, "console_errors": errors[:MAX_CONSOLE_MESSAGES],
         "blocked_external_requests": len(blocked),
         "note": "Sessão Chromium nova; não representa cookies/abas do navegador pessoal."}
    )


def inspect_window():
    """Require explicit mouse selection of a single X11 window after approval."""
    if os.name != "posix" or not os.environ.get("DISPLAY"):
        raise RuntimeError("Captura de janela exige uma sessão gráfica Linux com DISPLAY")
    if os.environ.get("XDG_SESSION_TYPE", "x11").lower() == "wayland":
        raise RuntimeError(
            "Seleção de janelas via X11 não disponível em Wayland. "
            "Use uma sessão X11; não será capturada a área de trabalho inteira."
        )
    for program in ("xwininfo", "import"):
        if not shutil.which(program):
            raise RuntimeError(
                "Programa necessário para capturar uma janela não encontrado: "
                + program + ". Instale x11-utils e imagemagick (no Linux Mint/Ubuntu)."
            )
    # xwininfo with no window id prompts the user to CLICK a target.
    try:
        picked = subprocess.run(
            ["xwininfo"], capture_output=True, text=True, timeout=60, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Seleção de janela cancelada após 60 segundos") from exc
    if picked.returncode:
        raise RuntimeError("Não foi possível selecionar a janela Linux")
    found = WINDOW_ID.search(picked.stdout)
    if not found:
        raise RuntimeError("Não foi possível identificar a janela selecionada")
    window_id = found.group(1)
    # Refuse the X11 root desktop window: only an explicitly selected app window.
    try:
        desktop = subprocess.run(
            ["xwininfo", "-root"], capture_output=True, text=True, timeout=8,
            check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Não foi possível validar a janela selecionada") from exc
    root_match = WINDOW_ID.search(desktop.stdout) if desktop.returncode == 0 else None
    if root_match is None:
        raise RuntimeError("Não foi possível validar a janela raiz do desktop")
    if int(window_id, 16) == int(root_match.group(1), 16):
        raise RuntimeError("Captura da área de trabalho inteira bloqueada: selecione uma janela")
    try:
        screenshot = subprocess.run(
            ["import", "-window", window_id, "-quality", "55", "jpeg:-"],
            capture_output=True, timeout=20, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Tempo excedido ao capturar janela") from exc
    if screenshot.returncode:
        raise RuntimeError(
            "Captura da janela falhou. Confira se ImageMagick está configurado "
            "para acesso ao servidor X11."
        )
    return make_image_result(
        screenshot.stdout, "window",
        {"window_selected": True,
         "note": "A imagem corresponde à janela selecionada; "
                 "não inclui DOM nem console de aplicações nativas."}
    )


def inspect(task):
    target = validate_target(task)
    if target["mode"] == "web":
        return inspect_web(target["url"])
    return inspect_window()

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--web-worker":
        raise SystemExit("Ação não suportada")
    try:
        print(json.dumps(inspect_web(sys.argv[2]), ensure_ascii=False))
    except Exception as exc:
        print("Erro no trabalhador Playwright: " + str(exc)[:400], file=sys.stderr)
        raise SystemExit(1)
