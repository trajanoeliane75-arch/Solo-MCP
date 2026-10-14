#!/usr/bin/env python3
"""Graphical bootstrap and XDG launcher; no terminal window or pip installs."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
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
    return ("[Desktop Entry]\nType=Application\nName=Solo-MCP\n"
            "Comment=Seus projetos, contexto e aprovações em um só lugar\n"
            "Terminal=false\nStartupNotify=true\nIcon=folder-remote\n"
            "Categories=Development;Utility;\n"
            "Exec=" + desktop_quote("/usr/bin/python3") + " " + desktop_quote(ROOT / "launch.py") + "\n")


def install_shortcut():
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    target = base / "applications" / "solo-mcp.desktop"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(desktop_entry(), encoding="utf-8")
    target.chmod(0o755)
    return target


def show_error(message):
    if shutil.which("zenity"):
        subprocess.run(["zenity", "--error", "--title=Solo-MCP", "--width=440", "--no-markup", "--text=" + message], check=False)
    else:
        # GTK is normally installed even when WebKit is missing.
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk
            dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR,
                                       buttons=Gtk.ButtonsType.CLOSE, text="Solo-MCP")
            dialog.format_secondary_text(message)
            dialog.run()
            dialog.destroy()
        except Exception:
            print(message, file=sys.stderr)


def ensure_runtime():
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.1")
        return True
    except (ImportError, ValueError):
        pass
    if not (shutil.which("zenity") and shutil.which("pkexec") and Path("/usr/bin/apt-get").exists()):
        show_error("Instale os componentes gráficos do sistema: " + ", ".join(DESKTOP_PACKAGES) + ". Consulte docs/GUI.md para outras distribuições.")
        return False
    consent = subprocess.run(["zenity", "--question", "--title=Preparar Solo-MCP", "--width=470",
                              "--ok-label=Instalar e abrir", "--cancel-label=Agora não", "--no-markup",
                              "--text=O Solo-MCP usa o motor WebKit do Linux para abrir sua interface.\n\nComponentes: " + ", ".join(DESKTOP_PACKAGES) + "\n\nO Linux solicitará autorização para instalar esses pacotes."], check=False)
    if consent.returncode:
        return False
    # Launch a visible progress window while the OS handles administrative consent.
    progress = subprocess.Popen(["zenity", "--progress", "--pulsate", "--auto-close", "--no-cancel",
                                 "--title=Preparando Solo-MCP", "--text=Instalando componentes gráficos…"], stdin=subprocess.PIPE)
    try:
        result = subprocess.run([shutil.which("pkexec"), "/usr/bin/apt-get", "install", "-y", *DESKTOP_PACKAGES],
                                capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        show_error("A instalação não foi concluída. Confira sua conexão e tente abrir novamente.")
        return False
    finally:
        progress.stdin.close()
        progress.wait()
    if result.returncode:
        show_error("A instalação não foi concluída. Abra novamente para tentar de novo.")
        return False
    os.execv("/usr/bin/python3", ["/usr/bin/python3", str(ROOT / "launch.py")])


def main():
    if "--install-only" in sys.argv:
        print(install_shortcut())
        return
    if not ensure_runtime():
        return
    install_shortcut()
    try:
        from solo_app import main as run
        run()
    except Exception as exc:
        show_error("Não foi possível abrir o Solo-MCP.\n\n" + str(exc)[:1000])


if __name__ == "__main__":
    main()
