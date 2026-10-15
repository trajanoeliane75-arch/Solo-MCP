#!/usr/bin/env python3
"""Graphical bootstrap and XDG launcher; no terminal window or pip installs."""
import os
from pathlib import Path
import shutil
import tempfile
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
ICON_NAME = "solo-agent"
ICON_SOURCE = ROOT / "share" / "icons"
ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)
DESKTOP_PACKAGES = ("python3-gi", "gir1.2-gtk-3.0", "gir1.2-webkit2-4.1", "xdg-utils")


def desktop_quote(value):
    # Exec escaping, followed by desktop-entry string escaping.
    value = str(value)
    if any(c in value for c in "\n\r\x00"):
        raise ValueError("Caminho inválido")
    value = value.replace("%", "%%")
    escaped = "".join("\\" + c if c in '\\"`$' else c for c in value)
    return '"' + escaped.replace("\\", "\\\\") + '"'


def desktop_entry():
    return ("[Desktop Entry]\nType=Application\nName=Solo\n"
            "Comment=Seus projetos, contexto e aprovações em um só lugar\n"
            "Terminal=false\nStartupNotify=true\nIcon=" + ICON_NAME + "\n"
            "Categories=Development;Utility;\n"
            "Exec=" + desktop_quote("/usr/bin/python3") + " " + desktop_quote(ROOT / "launch.py") + "\n")


def install_icons():
    """Install the bundled icon to the user's XDG theme; never require root."""
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    installed = []
    for size in ICON_SIZES:
        source = ICON_SOURCE / ("solo-" + str(size) + ".png")
        if not source.is_file():
            raise FileNotFoundError("Ícone do Solo ausente: " + source.name)
        directory = base / "icons" / "hicolor" / (str(size) + "x" + str(size)) / "apps"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (ICON_NAME + ".png")
        # Atomic replacement avoids truncated PNGs if the launcher is interrupted.
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".solo-icon-", delete=False) as f:
            temp = Path(f.name)
            try:
                f.write(source.read_bytes())
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                temp.unlink(missing_ok=True)
                raise
        try:
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        installed.append(target)
    scalable = ICON_SOURCE / "solo.svg"
    if scalable.is_file():
        directory = base / "icons" / "hicolor" / "scalable" / "apps"
        directory.mkdir(parents=True, exist_ok=True)
        # PNGs are the primary icon; scalable SVG is optional.
        (directory / (ICON_NAME + ".svg")).write_bytes(scalable.read_bytes())
    return installed


def install_shortcut():
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    install_icons()
    target = base / "applications" / "solo-mcp.desktop"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(desktop_entry(), encoding="utf-8")
    target.chmod(0o755)
    return target


def show_error(message):
    from solo_bootstrap_ui import show_error as native_error
    native_error(message)


def ensure_runtime():
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # GTK is usable before WebKit is installed.
    except (ImportError, ValueError):
        show_error("O GTK3 não está instalado. Instale python3-gi e gir1.2-gtk-3.0 "
                   "pelo gerenciador de pacotes do Linux e abra o Solo novamente.")
        return False
    try:
        gi.require_version("WebKit2", "4.1")
        from gi.repository import WebKit2
        return True
    except (ImportError, ValueError):
        pass
    if not (shutil.which("pkexec") and Path("/usr/bin/apt-get").is_file()):
        show_error("Instale os componentes gráficos: " + ", ".join(DESKTOP_PACKAGES)
                   + ". Consulte docs/GUI.md para sua distribuição.")
        return False
    from solo_bootstrap_ui import ask_consent, run_with_progress
    if not ask_consent(DESKTOP_PACKAGES):
        return False
    ok = run_with_progress(
        [shutil.which("pkexec"), "/usr/bin/apt-get", "install", "-y", *DESKTOP_PACKAGES],
        timeout=600,
    )
    if not ok:
        show_error("A instalação não foi concluída. Confira a conexão e "
                   "a autorização do Linux e tente novamente.")
        return False
    os.execv("/usr/bin/python3", ["/usr/bin/python3", str(ROOT / "launch.py")])


def main():
    if "--install-only" in sys.argv:
        print(install_shortcut())
        return
    try:
        install_shortcut()
    except (OSError, ValueError) as exc:
        show_error("Não foi possível registrar o atalho e o ícone do Solo: " + str(exc)[:200])
        return
    if not ensure_runtime():
        return
    try:
        from solo_app import main as run
        run()
    except Exception as exc:
        show_error("Não foi possível abrir o Solo.\n\n" + str(exc)[:1000])


if __name__ == "__main__":
    main()
