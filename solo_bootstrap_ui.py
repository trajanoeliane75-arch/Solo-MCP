"""Native GTK3 first-run screens for Solo, independent of WebKitGTK.

This file never installs software or requests elevated privileges by itself.
The launcher alone selects the fixed apt-get package list and invokes pkexec.
"""
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parent
_ICON = ROOT / "share" / "icons" / "solo-128.png"

_CSS = """
.solo-dialog, .solo-dialog box, .solo-dialog dialog {
    background-color: #ffffff;
    color: #141414;
}
.solo-dialog label { color: #141414; font-family: sans-serif; }
.solo-dialog .solo-title { font-size: 21px; font-weight: 600; }
.solo-dialog .solo-detail { color: #595959; font-size: 12px; }
.solo-dialog button {
    background-image: none;
    background-color: #ffffff;
    border: 1px solid #e8e8e5;
    border-radius: 22px;
    box-shadow: none;
    color: #141414;
    min-height: 26px;
    padding: 6px 17px;
}
.solo-dialog button.solo-primary {
    background-color: #141414;
    border-color: #141414;
    color: #ffffff;
}
.solo-dialog button:hover { border-color: #999999; }
.solo-dialog button.solo-primary:hover { background-color: #303030; }
.solo-dialog progressbar trough {
    background-color: #e8e8e5;
    border-radius: 6px;
    min-height: 8px;
}
.solo-dialog progressbar progress { background-color: #141414; border-radius: 6px; }
"""


def _gtk():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, GLib, Gtk
    return Gtk, GLib, Gdk


def _style(Gtk, Gdk):
    screen = Gdk.Screen.get_default()
    if screen:
        css = Gtk.CssProvider()
        css.load_from_data(_CSS.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def _dialog(title, message, details=""):
    Gtk, GLib, Gdk = _gtk()
    _style(Gtk, Gdk)
    dialog = Gtk.Dialog(title="Solo", flags=Gtk.DialogFlags.MODAL)
    dialog.get_style_context().add_class("solo-dialog")
    dialog.set_default_size(500, -1)
    dialog.set_resizable(False)
    dialog.set_border_width(20)
    dialog.set_deletable(True)
    if _ICON.is_file():
        try:
            dialog.set_icon_from_file(str(_ICON))
        except Exception:
            pass  # Do not block installing WebKit because of an icon loader.
    area = dialog.get_content_area()
    area.set_spacing(14)
    heading = Gtk.Label(label=title)
    heading.set_xalign(0)
    heading.get_style_context().add_class("solo-title")
    area.pack_start(heading, False, False, 0)
    body = Gtk.Label(label=message)
    body.set_xalign(0)
    body.set_line_wrap(True)
    body.set_max_width_chars(60)
    area.pack_start(body, False, False, 0)
    if details:
        detail = Gtk.Label(label=details)
        detail.set_xalign(0)
        detail.set_line_wrap(True)
        detail.set_max_width_chars(60)
        detail.get_style_context().add_class("solo-detail")
        area.pack_start(detail, False, False, 0)
    return Gtk, GLib, dialog, area


def _button(dialog, Gtk, label, response, primary=False):
    btn = dialog.add_button(label, response)
    if primary:
        btn.get_style_context().add_class("solo-primary")
        dialog.set_default_response(response)
    return btn


def ask_consent(packages):
    """Request explicit permission; False never starts a privileged process."""
    Gtk, _, dialog, _ = _dialog(
        "Preparar o Solo",
        "O Solo usa componentes gráficos do Linux para abrir a interface. "
        "Eles ainda não estão disponíveis neste computador.",
        "Componentes: " + ", ".join(packages) + ".\n\n"
        "O próprio Linux solicitará sua senha administrativa para a instalação. "
        "O Solo não recebe nem armazena essa senha.",
    )
    _button(dialog, Gtk, "Agora não", Gtk.ResponseType.CANCEL)
    _button(dialog, Gtk, "Instalar e abrir", Gtk.ResponseType.OK, primary=True)
    dialog.show_all()
    try:
        return dialog.run() == Gtk.ResponseType.OK
    finally:
        dialog.destroy()


def run_with_progress(command, timeout=600):
    """Show a responsive, non-cancellable progress dialog for fixed launcher command.

    Returns True only on successful subprocess exit. Never exposes captured
    subprocess output to the UI; detailed package-manager logs remain private.
    """
    Gtk, GLib, dialog, area = _dialog(
        "Preparando o Solo",
        "Instalando os componentes gráficos necessários…",
        "O Linux pode solicitar confirmação administrativa numa janela separada. "
        "Aguarde a conclusão da instalação.",
    )
    progress = Gtk.ProgressBar()
    progress.set_show_text(False)
    area.pack_start(progress, False, False, 10)
    dialog.set_deletable(False)
    dialog.connect("delete-event", lambda *_: True)
    outcome = {"success": False}

    def worker():
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout, check=False
            )
            outcome["success"] = completed.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            outcome["success"] = False
        GLib.idle_add(dialog.response, Gtk.ResponseType.OK)

    def pulse():
        progress.pulse()
        return True

    source = GLib.timeout_add(110, pulse)
    threading.Thread(target=worker, daemon=True).start()
    dialog.show_all()
    try:
        dialog.run()
    finally:
        GLib.source_remove(source)
        dialog.destroy()
    return outcome["success"]


def show_error(message):
    """A useful native error when GTK3 exists; stderr as a last-resort fallback."""
    try:
        Gtk, _, dialog, _ = _dialog("Não foi possível abrir o Solo", message)
        _button(dialog, Gtk, "Fechar", Gtk.ResponseType.CLOSE, primary=True)
        dialog.show_all()
        try:
            dialog.run()
        finally:
            dialog.destroy()
    except Exception:
        # GTK itself may be missing; do not try to use WebKit or Zenity.
        print("Solo: " + str(message), file=sys.stderr)
