"""Private, user-scoped essential-tool kit for Solo-MCP.

The app controls its own Playwright+Chromium runtime. No workspace or remote
issue is allowed to install packages here. Setup is called only by an explicit
local action (initial GUI onboarding or "Prepare/repair" button).
All subprocess commands are fixed, never shell strings or user-controlled pip.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PLAYWRIGHT_VERSION = "1.63.0"
KIT_RELEASE = 1
KIT_ROOT = Path.home() / ".local" / "share" / "solo-mcp" / "kit-v1"
NATIVE_PACKAGES = ("x11-utils", "imagemagick")
STATE_FILE = "kit-state.json"


def kit_python():
    return KIT_ROOT / "bin" / "python"


def browser_folder():
    return KIT_ROOT / "browsers"


def state_path():
    return KIT_ROOT / STATE_FILE


def private_directory():
    """Keep the kit in the current user's private data directory."""
    if KIT_ROOT.is_symlink():
        raise RuntimeError("O diretório do kit é um link simbólico. Operação bloqueada.")
    KIT_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    KIT_ROOT.chmod(0o700)
    if KIT_ROOT.resolve() != KIT_ROOT:
        raise RuntimeError("O caminho do kit não é canônico.")
    return KIT_ROOT


def browser_env():
    """Sanitize environment inherited by installer and browser subprocesses."""
    deny = ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY",
            "GITHUB", "GH_", "AWS_", "SSH_", "SOLO_MCP_", "OPENAI_", "PIP_")
    env = {
        k: v for k, v in os.environ.items()
        if not any(term in k.upper() for term in deny)
    }
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_folder())
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


def deferred_setup():
    return (KIT_ROOT / ".onboarding-deferred").exists()


def defer_setup():
    private_directory()
    marker = KIT_ROOT / ".onboarding-deferred"
    marker.touch(mode=0o600)
    marker.chmod(0o600)


def _record():
    try:
        value = json.loads(state_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def status():
    """Fast, local-only status; no installation or network calls."""
    data = _record()
    py = kit_python()
    correct = (
        py.is_file()
        and data.get("kit_release") == KIT_RELEASE
        and data.get("playwright") == PLAYWRIGHT_VERSION
        and data.get("browser_tested") is True
        and browser_folder().is_dir()
    )
    native = (
        bool(os.environ.get("DISPLAY"))
        and os.environ.get("XDG_SESSION_TYPE", "x11").lower() != "wayland"
        and bool(shutil.which("xwininfo"))
        and bool(shutil.which("import"))
    )
    return {
        "ready": bool(correct),
        "python": str(py),
        "browser": "pronto" if correct else "não preparado ou precisa de reparo",
        "playwright_version": PLAYWRIGHT_VERSION,
        "native_ready": native,
        "native": (
            "captura X11 disponível" if native
            else "requer sessão X11, x11-utils e ImageMagick"
        ),
    }


def _write_state():
    root = private_directory()
    record = json.dumps({
        "kit_release": KIT_RELEASE,
        "playwright": PLAYWRIGHT_VERSION,
        "browser_tested": True,
    }, ensure_ascii=False, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".kit-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(record)
        os.chmod(temporary, 0o600)
        os.replace(temporary, state_path())
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _run(argv, *, timeout, env=None):
    """Bounded, checked subprocess without shell or secret-bearing logs."""
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            check=False, env=env,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "Preparação do kit excedeu o tempo limite desta etapa."
        ) from error
    except OSError as error:
        raise RuntimeError(
            "Não foi possível iniciar uma etapa do kit: "
            + type(error).__name__
        ) from error
    if result.returncode != 0:
        # Dependencies might print URLs carrying credentials; avoid copying
        # their raw stderr into UI and logs.
        raise RuntimeError(
            "Etapa do kit falhou (código " + str(result.returncode)
            + "). Consulte as dependências do sistema e tente Reparar kit."
        )
    return result


def prepare(on_progress=None, *, repair=False):
    """Install internal Playwright + Chromium, then verify real browser launch.

    No sudo; no system changes; no workspace path mounted/modified.
    GUI must ask permission before calling this (downloads executable binaries).
    """
    def notice(text):
        if on_progress is not None:
            on_progress(text)

    if os.name != "posix" or sys.platform != "linux" or os.geteuid() == 0:
        raise RuntimeError("Instale o kit na sessão Linux do usuário, sem root.")
    private_directory()
    previous = status()
    if previous["ready"] and not repair:
        notice("Kit essencial já está pronto.")
        return previous

    env = browser_env()
    py = kit_python()
    if not py.is_file():
        notice("Criando ambiente privado do Solo-MCP...")
        _run(
            [sys.executable, "-m", "venv", str(KIT_ROOT)],
            timeout=130, env=env,
        )
    if not py.is_file():
        raise RuntimeError(
            "Python venv não ficou disponível. O sistema pode precisar do "
            "pacote python3-venv, instalado com autorização administrativa."
        )

    notice("Instalando Playwright no kit interno...")
    # --isolated ignores user pip config and environment; fixed public index.
    _run(
        [str(py), "-m", "pip", "--isolated", "install", "--no-input",
         "--disable-pip-version-check", "--index-url",
         "https://pypi.org/simple", "playwright==" + PLAYWRIGHT_VERSION],
        timeout=360, env=env,
    )

    notice("Preparando Chromium para inspeções...")
    # The browser resides in the private KIT_ROOT/browsers directory.
    _run(
        [str(py), "-m", "playwright", "install", "chromium"],
        timeout=600, env=env,
    )

    notice("Validando Chromium com uma abertura de teste...")
    probe = (
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        " b=p.chromium.launch(headless=True)\n"
        " page=b.new_page()\n"
        " page.goto('about:blank')\n"
        " assert page.title()==''\n"
        " b.close()\n"
    )
    _run([str(py), "-c", probe], timeout=50, env=env)
    _write_state()
    (KIT_ROOT / ".onboarding-deferred").unlink(missing_ok=True)
    notice("Playwright e Chromium prontos no kit privado.")
    return status()


def native_missing():
    return [program for program in ("xwininfo", "import")
            if shutil.which(program) is None]


def system_package_plan():
    """Fixed Debian/Ubuntu packages, no arbitrary user-specified commands."""
    if not native_missing():
        return None
    if not Path("/usr/bin/apt-get").is_file():
        return None
    privilege = shutil.which("pkexec")
    if not privilege:
        return None
    return [privilege, "/usr/bin/apt-get", "install", "-y", *NATIVE_PACKAGES]


def prepare_native(on_progress=None):
    """Requires a *separate* explicit GUI consent and OS authentication."""
    if not native_missing():
        return status()
    command = system_package_plan()
    if command is None:
        raise RuntimeError(
            "Instalação automática das dependências X11 indisponível neste Linux. "
            "O modo web continua utilizável; dependências nativas pendentes."
        )
    if on_progress:
        on_progress("Solicitando autorização administrativa para pacotes X11...")
    _run(command, timeout=420)
    if native_missing():
        raise RuntimeError("Pacotes X11 não ficaram disponíveis após a instalação.")
    return status()
