#!/usr/bin/env python3
"""Single-instance Linux desktop shell using the system WebKitGTK engine."""
import json
from pathlib import Path
import sys
import threading

from solo_ui import AppBackend

UI_ROOT = Path(__file__).resolve().parent / "ui"


def create_application(initial_page="home", backend=None, application_id="io.github.solo_mcp.Desktop"):
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import Gio, GLib, Gtk, WebKit2

    class SoloApplication(Gtk.Application):
        def __init__(self):
            super().__init__(application_id=application_id, flags=Gio.ApplicationFlags.FLAGS_NONE)
            self.window = None
            self.closed = False
            self.backend = backend or AppBackend(choose_folder=self.choose_folder)
            if hasattr(self.backend, "on_pending"):
                self.backend.on_pending = lambda count: GLib.idle_add(self.notify_pending, count)

        def notify_pending(self, count):
            if not self.closed and count > 0:
                notice = Gio.Notification.new("Nova solicitação no Solo-MCP")
                notice.set_body(
                    "Há uma tarefa aguardando sua autorização. Abra Aprovações."
                    if count == 1 else
                    f"Há {count} tarefas aguardando autorização. Abra Aprovações."
                )
                try:
                    self.send_notification("solo-mcp-pending", notice)
                except Exception:
                    pass  # Notifications are optional; approvals remain visible.
            return False

        def do_activate(self):
            if self.window:
                self.window.present()
                return
            self.window = Gtk.ApplicationWindow(application=self, title="Solo-MCP")
            self.window.set_default_size(1200, 800)
            self.window.set_size_request(760, 560)
            self.window.set_icon_name("folder-remote")
            self.window.connect("delete-event", self.request_close)
            manager = WebKit2.UserContentManager()
            manager.connect("script-message-received::solo", self.receive)
            manager.register_script_message_handler("solo")
            self.view = WebKit2.WebView.new_with_user_content_manager(manager)
            settings = self.view.get_settings()
            settings.set_enable_developer_extras(False)
            settings.set_allow_file_access_from_file_urls(False)
            settings.set_allow_universal_access_from_file_urls(False)
            self.view.connect("decide-policy", self.navigation_policy)
            self.view.connect("permission-request", lambda view, request: (request.deny(), True)[1])
            self.view.connect("context-menu", lambda *args: True)
            self.view.connect("load-changed", self.loaded)
            self.window.add(self.view)
            self.view.load_uri((UI_ROOT / "index.html").as_uri())
            self.window.show_all()

        def navigation_policy(self, view, decision, kind):
            if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
                uri = decision.get_navigation_action().get_request().get_uri()
                if uri.split("#")[0] != (UI_ROOT / "index.html").as_uri() or kind == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
                    decision.ignore()
                    return True
            return False

        def loaded(self, view, event):
            if event == WebKit2.LoadEvent.FINISHED and initial_page != "home":
                self.evaluate("window.soloInitialPage=" + json.dumps(initial_page) + ";window.dispatchEvent(new Event('solo-route'));")

        def evaluate(self, script):
            if not self.closed:
                self.view.evaluate_javascript(script, -1, None, None, None, None, None)
            return False

        def receive(self, manager, message):
            if self.view.get_uri().split("#")[0] != (UI_ROOT / "index.html").as_uri():
                return
            raw = message.get_js_value().to_string()
            if len(raw) > 100000:
                return
            try:
                request = json.loads(raw)
                request_id = request["id"]
                if type(request_id) is not int:
                    return
                if request["method"] == "close_window":
                    self.closed = True
                    self.window.destroy()
                    self.quit()
                    return
            except (ValueError, KeyError, TypeError):
                return
            def worker():
                try:
                    result = self.backend.dispatch(request["method"], request.get("params"))
                    reply = {"id": request_id, "result": result}
                except Exception as exc:
                    reply = {"id": request_id, "error": str(exc)[:1600]}
                GLib.idle_add(self.evaluate, "window.soloResolve(" + json.dumps(reply, ensure_ascii=True) + ")")
            threading.Thread(target=worker, daemon=True).start()

        def choose_folder(self):
            done = threading.Event()
            result = {"folder": "", "error": ""}
            holder = {"dialog": None}
            def show():
                try:
                    dialog = Gtk.FileChooserDialog(
                        title="Escolher pasta do workspace", transient_for=self.window,
                        action=Gtk.FileChooserAction.SELECT_FOLDER)
                    holder["dialog"] = dialog
                    dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL,
                                       "Selecionar pasta", Gtk.ResponseType.ACCEPT)
                    dialog.set_modal(True)
                    dialog.set_local_only(True)
                    dialog.set_default_size(760, 520)
                    def response(widget, response_id):
                        try:
                            if response_id == Gtk.ResponseType.ACCEPT:
                                result["folder"] = widget.get_filename() or ""
                        finally:
                            widget.destroy()
                            done.set()
                    dialog.connect("response", response)
                    dialog.show_all()
                    dialog.present()
                except Exception:
                    result["error"] = "Não foi possível abrir a seleção de pastas. Digite o caminho da pasta manualmente."
                    done.set()
                return False
            GLib.idle_add(show)
            if not done.wait(120):
                def close_timed_out():
                    if holder["dialog"] is not None:
                        holder["dialog"].destroy()
                    return False
                GLib.idle_add(close_timed_out)
                raise RuntimeError("A seleção de pasta demorou demais. Tente novamente ou digite o caminho manualmente.")
            if result["error"]:
                raise RuntimeError(result["error"])
            return result["folder"]

        def request_close(self, *_):
            self.evaluate("window.soloRequestClose && window.soloRequestClose()")
            return True

    return SoloApplication()


def main(initial_page="home"):
    return create_application(initial_page).run([sys.argv[0]])


if __name__ == "__main__":
    main()
