"""Checks for the branded first-run installer and XDG application icon."""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock

import launch
import solo_bootstrap_ui as native


class BootstrapTests(unittest.TestCase):
    def test_application_icon_is_real_and_installed_at_all_sizes(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"XDG_DATA_HOME": directory}):
            shortcut = launch.install_shortcut()
            content = shortcut.read_text(encoding="utf-8")
            self.assertIn("Name=Solo\n", content)
            self.assertIn("Icon=solo-agent\n", content)
            self.assertNotIn("Icon=folder-remote", content)
            self.assertIn("launch.py", content)
            for size in launch.ICON_SIZES:
                target = Path(directory) / "icons/hicolor" / f"{size}x{size}" / "apps/solo-agent.png"
                self.assertEqual(target.read_bytes(), (launch.ICON_SOURCE / f"solo-{size}.png").read_bytes())
            self.assertTrue((Path(directory) / "icons/hicolor/scalable/apps/solo-agent.svg").exists())

    def test_launcher_requires_a_real_gtk_consent_and_no_zenity(self):
        self.assertNotIn("zenity", Path(launch.__file__).read_text().lower())
        self.assertIn("pkexec", Path(launch.__file__).read_text())
        self.assertEqual(native.ask_consent.__name__, "ask_consent")

    def test_consent_cancel_never_approves(self):
        class Responses:
            OK = 1
            CANCEL = 0
        class Gtk:
            ResponseType = Responses
        class Dialog:
            def __init__(self, result): self.result = result; self.destroyed = False
            def show_all(self): pass
            def run(self): return self.result
            def destroy(self): self.destroyed = True
        for response, expected in [(0, False), (1, True)]:
            dialog = Dialog(response)
            with self.subTest(response=response), patch.object(native, "_dialog", return_value=(Gtk, None, dialog, None)), patch.object(native, "_button"):
                self.assertIs(native.ask_consent(("pkg1",)), expected)
                self.assertTrue(dialog.destroyed)

    def test_progress_reports_success_or_failure_without_needing_webkit(self):
        class Responses:
            OK = 1
        class Gtk:
            ResponseType = Responses
            @staticmethod
            def ProgressBar():
                return MagicMock()
        class Area:
            def pack_start(self, *args): pass
        class Dialog:
            def __init__(self): self.done = threading.Event()
            def set_deletable(self, *args): pass
            def connect(self, *args): pass
            def show_all(self): pass
            def response(self, *_): self.done.set()
            def run(self):
                if not self.done.wait(4): raise AssertionError("worker never finished")
            def destroy(self): pass
        class GLib:
            @staticmethod
            def timeout_add(*args): return 1
            @staticmethod
            def idle_add(callback, *args): callback(*args)
            @staticmethod
            def source_remove(*args): pass
        for returncode, expected in [(0, True), (1, False)]:
            dialog = Dialog()
            with self.subTest(returncode=returncode), patch.object(native, "_dialog", return_value=(Gtk, GLib, dialog, Area())), patch.object(native.subprocess, "run", return_value=MagicMock(returncode=returncode)):
                self.assertIs(native.run_with_progress(["program", "arg"], timeout=2), expected)


if __name__ == "__main__":
    unittest.main()
