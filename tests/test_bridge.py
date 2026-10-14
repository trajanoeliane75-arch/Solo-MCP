import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import zipfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import solo_mcp as sm

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = {'control_repo': 'owner/private', 'projects': {'test': {'path': str(self.root)}}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_and_list(self):
        (self.root / 'hello.txt').write_text('olá')
        self.assertIn('hello.txt', [x['name'] for x in sm.do_task(self.config, {'version':1, 'project':'test','action':'list','path':'.'})['entries']])
        self.assertEqual(sm.do_task(self.config, {'version':1,'project':'test','action':'read','path':'hello.txt'})['content'], 'olá')

    def test_archive_list(self):
        with zipfile.ZipFile(self.root / 'sdk.jar', 'w') as z:
            z.writestr('com/solo/Usb.class', 'abcd')
        files = sm.do_task(self.config, {'version':1, 'project':'test', 'action':'archive_list', 'path':'sdk.jar'})['entries']
        self.assertEqual(files[0]['name'], 'com/solo/Usb.class')

    def test_guard(self):
        for path in ('../secret', '/etc/passwd', '.ssh/id_rsa', '.env'):
            with self.assertRaises(ValueError):
                sm.safe_path(self.root, path)
        outside = self.root.parent / 'escape-bridge-test'
        (self.root / 'link').symlink_to(outside)
        with self.assertRaises(ValueError):
            sm.safe_path(self.root, 'link')

    def test_parse_task(self):
        self.assertIsNone(sm.parse_task('hello'))
        self.assertIsNotNone(sm.parse_task(sm.MARKER + '\n' + json.dumps({'version':1,'project':'x','action':'list'})))

    def test_approve_sn(self):
        for response in ('s', 'S', ' s ', ' S '):
            with self.subTest(response=response):
                with patch('builtins.input', return_value=response):
                    self.assertTrue(sm.approve('Operação de teste'))
        for response in ('n', 'N', '', 'aprovar', 'sim', 'qualquer'):
            with self.subTest(response=response):
                with patch('builtins.input', return_value=response):
                    self.assertFalse(sm.approve('Operação de teste'))

    def test_write_requires_expected_sha(self):
        (self.root/'existing.txt').write_text('old')
        with self.assertRaises(ValueError):
            sm.do_task(self.config, {'version':1,'project':'test','action':'write','path':'existing.txt','content':'new'})

    def test_serve_silently_while_idle(self):
        with patch.object(sm, 'process_once', side_effect=[0, 2]) as process, \
             patch.object(sm.time, 'sleep', side_effect=[None, KeyboardInterrupt]) as sleep, \
             patch('builtins.print') as output:
            with self.assertRaises(KeyboardInterrupt):
                sm.serve_tasks(self.config, object(), interval=10)
        self.assertEqual(process.call_count, 2)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual([call.args[0] for call in output.call_args_list],
                         ['Tarefas executadas: 2'])

    def test_serve_once_does_not_spam_zero(self):
        with patch.object(sm, 'process_once', return_value=0) as process, \
             patch.object(sm.time, 'sleep') as sleep, \
             patch('builtins.print') as output:
            sm.serve_tasks(self.config, object(), once=True)
        process.assert_called_once()
        sleep.assert_not_called()
        output.assert_not_called()

    def test_private_guard(self):
        class Stub:
            def request(self, method, endpoint):
                return {'private': False}
        with self.assertRaises(RuntimeError):
            sm.require_private_repo(Stub(), 'owner/public')

if __name__ == '__main__':
    unittest.main()
