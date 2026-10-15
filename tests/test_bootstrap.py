"""Regression tests: Solo installer identity, consent, progress, safe fallback."""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import launch
import solo_bootstrap_ui as native


class Widget:
    def __init__(self, label=''):
        self.label = label
        self.handlers = {}
        self.destroyed = False
        self.properties = []
    def get_style_context(self): return self
    def add_class(self, name): self.properties.append(name)
    def connect(self, event, cb): self.handlers[event] = cb
    def destroy(self):
        self.destroyed = True
        if 'destroy' in self.handlers: self.handlers['destroy'](self)
    def pack_start(self, *_): pass
    def set_halign(self, *_): pass
    def set_deletable(self, *_): pass
    def pulse(self): pass
    def emit(self, event): return self.handlers[event](self)


class BootstrapTests(unittest.TestCase):
    def test_application_icon_is_real_and_installed_at_all_sizes(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_DATA_HOME': directory}):
            shortcut = launch.install_shortcut()
            content = shortcut.read_text(encoding='utf-8')
            self.assertIn('Name=Solo\n', content)
            self.assertIn('Icon=solo-agent\n', content)
            self.assertNotIn('Icon=folder-remote', content)
            for size in launch.ICON_SIZES:
                target = Path(directory) / 'icons/hicolor' / f'{size}x{size}' / 'apps/solo-agent.png'
                self.assertEqual(target.read_bytes(), (launch.ICON_SOURCE / f'solo-{size}.png').read_bytes())

    def test_launcher_keeps_consent_privileges_and_timeout(self):
        source = Path(launch.__file__).read_text(encoding='utf8')
        self.assertNotIn('zenity', source.lower())
        self.assertIn('pkexec', source)
        self.assertIn('timeout=600', source)
        self.assertIn('if not ask_consent(DESKTOP_PACKAGES)', source)
        self.assertIn('os.execv(', source)

    def test_designer_tokens_and_text_preserved(self):
        self.assertIn('font-size: 19px; font-weight: 300', native.CSS)
        self.assertIn('border-radius: 999px', native.CSS)
        self.assertIn('min-height: 2px', native.CSS)
        self.assertIn('#e8e8e5', native.CSS)
        self.assertNotIn('Gtk.main_quit()\n', Path(native.__file__).read_text())

    def _mock_gtk(self):
        buttons = []
        def make_button(label):
            w = Widget(label)
            buttons.append(w)
            return w
        Gtk = SimpleNamespace(Button=make_button, Box=lambda **kw:Widget(),
            Align=SimpleNamespace(END='end'), Orientation=SimpleNamespace(HORIZONTAL='h'))
        window = Widget()
        with patch.object(native, '_gtk', return_value=(Gtk, None, None)), \
             patch.object(native, '_shell', return_value=(window, Widget())), \
             patch.object(native, '_label', return_value=Widget()), \
             patch.object(native, '_divider', return_value=Widget()):
            yield buttons,window

    def test_consent_cancel_does_not_authorize(self):
        for selected,expected in [('Agora não',False),('Instalar e abrir',True),(None,False)]:
            with self.subTest(selected=selected):
                for buttons, win in self._mock_gtk():
                    def click(w,glib):
                        if selected:
                            next(b for b in buttons if b.label==selected).emit('clicked')
                        else: w.destroy()
                    with patch.object(native, '_run_window', side_effect=click):
                        self.assertIs(native.ask_consent(['pkg1']),expected)
                        self.assertTrue(win.destroyed)

    def test_progress_cannot_be_dismissed_and_observes_exit_code(self):
        class Loop:
            def __init__(self): self.done=threading.Event()
            def run(self):
                if not self.done.wait(3): raise AssertionError('worker never finished')
            def quit(self): self.done.set()
        GLib=SimpleNamespace(MainLoop=Loop, timeout_add=lambda *x:17,
            idle_add=lambda fn:fn(),source_remove=MagicMock())
        Gtk=SimpleNamespace(ProgressBar=Widget)
        for returncode,expected in [(0,True),(1,False)]:
            with self.subTest(returncode=returncode):
                win=Widget()
                win.show_all=lambda:None
                with patch.object(native,'_gtk',return_value=(Gtk,GLib,None)), \
                     patch.object(native,'_shell',return_value=(win,Widget())), \
                     patch.object(native,'_label',return_value=Widget()), \
                     patch.object(native.subprocess,'run',return_value=SimpleNamespace(returncode=returncode)) as run:
                    self.assertIs(native.run_with_progress(['mock-exec'],timeout=5),expected)
                    self.assertTrue(win.destroyed)
                    self.assertTrue(win.emit('delete-event'))
                    run.assert_called_once()
                    self.assertEqual(run.call_args.kwargs['timeout'],5)

    def test_error_falls_back_if_gtk_unavailable(self):
        with patch.object(native, '_gtk', side_effect=ImportError('not installed')):
            with patch('sys.stderr') as stream:
                native.show_error('Teste de falha')
                self.assertTrue(any('Teste de falha' in str(call.args[0]) for call in stream.write.call_args_list))


if __name__=='__main__':unittest.main()
