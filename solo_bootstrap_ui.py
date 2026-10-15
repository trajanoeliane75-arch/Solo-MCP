"""Native GTK3 first-run screens, styled to the Solo art direction.

Based on the original Solo design supplied by the user. No WebKit dependency.
This module never authorizes a privileged operation or chooses packages:
launch.py retains explicit consent, its fixed pkexec/apt-get command and timeout.
"""
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parent
_ICON = ROOT / 'share' / 'icons' / 'solo-128.png'

# Solo light-theme tokens supplied by the designer (GTK CSS, not WebKit CSS).
BG = '#ffffff'
TEXT = '#141414'
MUTED = '#8f8f8c'
BORDER = '#e8e8e5'
INK = '#141414'
ON_INK = '#ffffff'
CSS = f'''
window.solo-bootstrap {{ background-color: {BG}; }}
.solo-eyebrow {{ color: {MUTED}; font-size: 10px; font-weight: 500; }}
.solo-title {{ color: {TEXT}; font-size: 19px; font-weight: 300; }}
.solo-body {{ color: {MUTED}; font-size: 13px; }}
.solo-divider {{ background-color: {BORDER}; min-height: 1px; }}
button.solo-primary {{
  background-image: none; box-shadow: none;
  background-color: {INK}; color: {ON_INK};
  border: 1px solid {INK}; border-radius: 999px;
  padding: 9px 18px; font-size: 12.5px; font-weight: 500;
}}
button.solo-primary:hover {{ background-color: #3a3a35; border-color: #3a3a35; }}
button.solo-ghost {{
  background-image: none; box-shadow: none;
  background-color: transparent; color: {MUTED};
  border: none; padding: 9px 4px;
  font-size: 12.5px; font-weight: 500;
}}
button.solo-ghost:hover {{ color: {TEXT}; }}
progressbar.solo-progress trough {{
  background-color: {BORDER}; min-height: 2px;
  border: none; border-radius: 0; box-shadow: none;
}}
progressbar.solo-progress progress {{
  background-color: {INK}; min-height: 2px;
  border: none; border-radius: 0; box-shadow: none;
}}
'''

_provider = None


def _gtk():
    # Lazy import: show_error() must still work on machines missing PyGObject.
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gtk, GLib, Gdk
    return Gtk, GLib, Gdk


def _ensure_css(Gtk, Gdk):
    global _provider
    screen = Gdk.Screen.get_default()
    if screen is None:
        return
    if _provider is None:
        _provider = Gtk.CssProvider()
        _provider.load_from_data(CSS.encode('utf-8'))
    Gtk.StyleContext.add_provider_for_screen(
        screen, _provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def _label(Gtk, text, css_class, wrap=True):
    label = Gtk.Label(label=text)
    label.get_style_context().add_class(css_class)
    label.set_xalign(0.0)
    if wrap:
        label.set_line_wrap(True)
        label.set_max_width_chars(44)
    return label


def _divider(Gtk):
    bar = Gtk.Box()
    bar.get_style_context().add_class('solo-divider')
    bar.set_size_request(-1, 1)
    return bar


def _shell(Gtk, Gdk, title):
    _ensure_css(Gtk, Gdk)
    win = Gtk.Window(title=title)
    win.get_style_context().add_class('solo-bootstrap')
    win.set_default_size(420, -1)
    win.set_resizable(False)
    win.set_position(Gtk.WindowPosition.CENTER)
    if _ICON.is_file():
        try:
            win.set_icon_from_file(str(_ICON))
        except Exception:
            pass  # Icon availability never blocks first-run setup.
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
    outer.set_border_width(32)
    win.add(outer)
    return win, outer


def _run_window(win, GLib):
    # A dedicated loop prevents the original double Gtk.main_quit() calls.
    loop = GLib.MainLoop()
    win.connect('destroy', lambda *_: loop.quit())
    win.show_all()
    loop.run()


def ask_consent(packages):
    """Explicit first-run consent. Closing the window means refusing."""
    Gtk, GLib, Gdk = _gtk()
    win, body = _shell(Gtk, Gdk, 'Preparar Solo')
    body.pack_start(_label(Gtk, 'PRIMEIRA ABERTURA', 'solo-eyebrow'), False, False, 0)
    body.pack_start(_label(Gtk, 'Solo usa o motor gráfico do seu sistema.', 'solo-title'), False, False, 0)
    body.pack_start(_label(
        Gtk, 'Para abrir a interface, faltam estes componentes: '
        + ', '.join(packages)
        + '. O Linux vai pedir sua autorização administrativa.', 'solo-body'
    ), False, False, 0)
    body.pack_start(_divider(Gtk), False, False, 6)
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    row.set_halign(Gtk.Align.END)
    cancel = Gtk.Button(label='Agora não')
    cancel.get_style_context().add_class('solo-ghost')
    install = Gtk.Button(label='Instalar e abrir')
    install.get_style_context().add_class('solo-primary')
    row.pack_start(cancel, False, False, 0)
    row.pack_start(install, False, False, 0)
    body.pack_start(row, False, False, 0)
    result = {'approved': False}
    cancel.connect('clicked', lambda *_: win.destroy())
    install.connect('clicked', lambda *_: (result.__setitem__('approved', True), win.destroy()))
    _run_window(win, GLib)
    return result['approved']


def run_with_progress(command, timeout=600):
    """Present the Claude-style 2px progress line during the launcher's fixed command.

    The window cannot be dismissed until the subprocess finishes. This fixes a
    designer-code bug that otherwise allowed closing it while apt was running.
    """
    Gtk, GLib, Gdk = _gtk()
    win, body = _shell(Gtk, Gdk, 'Preparando Solo')
    body.pack_start(_label(Gtk, 'INSTALANDO', 'solo-eyebrow'), False, False, 0)
    body.pack_start(_label(Gtk, 'Instalando componentes gráficos…', 'solo-title'), False, False, 0)
    progress = Gtk.ProgressBar()
    progress.get_style_context().add_class('solo-progress')
    body.pack_start(progress, False, False, 10)
    win.set_deletable(False)
    win.connect('delete-event', lambda *_: True)
    result = {'success': False}
    loop = GLib.MainLoop()
    win.connect('destroy', lambda *_: loop.quit())

    def _finish():
        win.destroy()
        return False

    def _worker():
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True,
                timeout=timeout, check=False,
            )
            result['success'] = completed.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            result['success'] = False
        finally:
            GLib.idle_add(_finish)

    def _pulse():
        progress.pulse()
        return True

    pulse_id = GLib.timeout_add(120, _pulse)
    win.show_all()
    threading.Thread(target=_worker, daemon=True).start()
    try:
        loop.run()
    finally:
        GLib.source_remove(pulse_id)
    return result['success']


def show_error(message):
    """Designer error state; fall back to stderr when GTK is not available."""
    try:
        Gtk, GLib, Gdk = _gtk()
        win, body = _shell(Gtk, Gdk, 'Solo')
        body.pack_start(_label(Gtk, 'NÃO FOI POSSÍVEL CONTINUAR', 'solo-eyebrow'), False, False, 0)
        body.pack_start(_label(Gtk, str(message), 'solo-body'), False, False, 0)
        body.pack_start(_divider(Gtk), False, False, 6)
        row = Gtk.Box()
        row.set_halign(Gtk.Align.END)
        ok = Gtk.Button(label='Entendi')
        ok.get_style_context().add_class('solo-primary')
        ok.connect('clicked', lambda *_: win.destroy())
        row.pack_start(ok, False, False, 0)
        body.pack_start(row, False, False, 0)
        _run_window(win, GLib)
    except (ImportError, ValueError, RuntimeError):
        print('Solo: ' + str(message), file=sys.stderr)
