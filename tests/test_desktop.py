import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import solo_mcp as sm
import solo_desktop as gui


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.conf = {'control_repo':'owner/private','projects':{'test':{'path':str(self.root),'permissions':{'read':True,'write':True,'terminal':True,'desktop':True,'environment':True}}}}
        self.write_task = {'version':1,'project':'test','action':'write','path':'hello.txt',
                           'content':'hello world','expected_sha256':None}

    def tearDown(self):
        self.temp.cleanup()

    def test_fingerprint_stable_and_sensitive(self):
        a = {'version':1,'action':'write','content':'a'}
        b = {'content':'a','action':'write','version':1}
        self.assertEqual(gui.fingerprint(a),gui.fingerprint(b))
        self.assertNotEqual(gui.fingerprint(a),gui.fingerprint({**a,'content':'b'}))

    def test_no_background_mutations(self):
        self.assertTrue({'write','run','open_app','web_search','doc_append','doc_create',
                         'venv_create','open_document'} <= sm.MUTATING_ACTIONS)
        class Gh:
            def request(self, method, url, data=None):
                if url=='/repos/owner/private':
                    return {'private':True,'owner':{'login':'owner'}}
                if '/issues?' in url:
                    return [{'number':5,'user':{'login':'owner'},
                             'body':sm.MARKER+'\n'+json.dumps(self_task)}]
                raise AssertionError(url)
        for action in sm.MUTATING_ACTIONS:
            self_task = {**self.write_task,'action':action}
            with self.subTest(action=action), patch.object(sm,'do_task') as execute:
                self.assertEqual(sm.process_once(self.conf,Gh(),background=True),0)
                execute.assert_not_called()

    def test_gui_filters_non_owner_and_readonly(self):
        class Gh:
            def request(self, method, url):
                if url=='/repos/owner/private':
                    return {'private':True,'owner':{'login':'owner'}}
                return [
                    {'number':1,'user':{'login':'owner'},'body':sm.MARKER+'\n'+json.dumps(self_task)},
                    {'number':2,'user':{'login':'other'},'body':sm.MARKER+'\n'+json.dumps(self_task)},
                    {'number':3,'user':{'login':'owner'},'body':sm.MARKER+'\n'+json.dumps({**self_task,'action':'list'})}
                ]
        self_task = self.write_task
        items = gui.pending_details(self.conf,Gh())
        self.assertEqual([i['number'] for i in items],[1])

    def test_tampered_preview_rejected(self):
        task = self.write_task
        class Gh:
            def request(self,method,url,data=None):
                if url=='/repos/owner/private':return {'private':True,'owner':{'login':'owner'}}
                if url.endswith('/issues/9'):
                    return {'state':'open','user':{'login':'owner'},
                            'body':sm.MARKER+'\n'+json.dumps({**task,'content':'TAMPERED'})}
                raise AssertionError('No further calls expected')
        with patch.object(sm,'do_task') as execute:
            with self.assertRaisesRegex(ValueError,'Tarefa mudou'):
                gui.decide(self.conf,Gh(),9,gui.fingerprint(task),True)
            execute.assert_not_called()

    def test_gui_reject_writes_result(self):
        task=self.write_task
        calls=[]
        class Gh:
            def request(self,method,url,data=None):
                calls.append((method,url,data))
                if url=='/repos/owner/private':return {'private':True,'owner':{'login':'owner'}}
                if url.endswith('/issues/4'):
                    if method=='PATCH':return {}
                    return {'state':'open','user':{'login':'owner'},
                            'body':sm.MARKER+'\n'+json.dumps(task)}
                if url.endswith('/comments?per_page=100'):return []
                if url.endswith('/comments'):return {}
                raise AssertionError(url)
        with patch.object(sm,'do_task') as execute:
            result=gui.decide(self.conf,Gh(),4,gui.fingerprint(task),False)
            execute.assert_not_called()
        self.assertEqual(result['result']['status'],'rejected')
        self.assertEqual(len([c for c in calls if c[0]=='POST']),1)
        self.assertEqual(len([c for c in calls if c[0]=='PATCH']),1)

    def test_write_with_injected_approval(self):
        with patch('builtins.input',side_effect=AssertionError('No terminal allowed')):
            result=sm.do_task(self.conf,self.write_task,approval_callback=lambda desc: True)
        self.assertEqual(result['status'],'written')
        self.assertEqual((self.root/'hello.txt').read_text(),'hello world')

    def test_google_search_url_and_approval(self):
        task={'version':1,'project':'test','action':'web_search','query':'capas celular Recife'}
        with patch.object(sm.subprocess,'Popen') as process:
            result=sm.do_task(self.conf,task,approval_callback=lambda desc:True)
        self.assertIn('capas+celular+Recife',result['url'])
        self.assertEqual(process.call_args.args[0][0],'xdg-open')

    def test_open_app_restricted(self):
        with self.assertRaises(ValueError):
            sm.do_task(self.conf,{'version':1,'project':'test','action':'open_app',
                                  'app':'/bin/sh'},approval_callback=lambda _:True)

    def test_autostart_private_location(self):
        with patch.dict('os.environ',{'XDG_CONFIG_HOME':str(self.root)}):
            gui.manage_autostart('install')
            path=gui.autostart_path()
            self.assertTrue(path.is_file())
            self.assertIn('launch.py',path.read_text())
            self.assertIn('Terminal=false',path.read_text())
            gui.manage_autostart('uninstall')
            self.assertFalse(path.exists())

    def test_docx_requires_existing_when_appending(self):
        task={'version':1,'project':'test','action':'doc_append','path':'report.docx','text':'some text'}
        with self.assertRaisesRegex(ValueError,'Documento inexistente'):
            sm.do_task(self.conf,task,approval_callback=lambda _:True)


if __name__=='__main__':
    unittest.main()
