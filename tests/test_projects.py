import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import solo_projects as sp
import solo_mcp as sm


class ProjectPermissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.a = self.base / 'project-A'
        self.b = self.base / 'project-B'
        self.a.mkdir()
        self.b.mkdir()
        (self.a / 'test.txt').write_text('test', encoding='utf-8')
        self.conf = {'control_repo':'owner/private', 'projects': {}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_are_read_only(self):
        project = sp.register_project(self.conf,'test',self.a,'owner/repo')
        self.assertEqual(project['permissions'],{
            'read':True,'write':False,'terminal':False,'desktop':False,'environment':False
        })

    def test_legacy_config_is_read_only(self):
        self.conf['projects']['legacy']={'path':str(self.a)}
        sp.check_permission(self.conf,'legacy','list')
        sp.check_permission(self.conf,'legacy','read')
        for action in ('write','run','open_app','doc_create','doc_append','sandbox_install','sandbox_run'):
            with self.subTest(action=action), self.assertRaises(PermissionError):
                sp.check_permission(self.conf,'legacy',action)

    def test_explicit_permissions_gate_actions(self):
        sp.register_project(self.conf,'test',self.a)
        sp.set_permissions(self.conf,'test','read,write')
        sp.check_permission(self.conf,'test','write')
        sp.check_permission(self.conf,'test','doc_append')
        for action in ('run','web_search','venv_create','sandbox_install'):
            with self.subTest(action=action), self.assertRaises(PermissionError):
                sp.check_permission(self.conf,'test',action)

    def test_terminal_does_not_automatically_grant_write(self):
        sp.register_project(self.conf,'test',self.a)
        sp.set_permissions(self.conf,'test','read,terminal')
        sp.check_permission(self.conf,'test','run')
        with self.assertRaises(PermissionError):
            sp.check_permission(self.conf,'test','write')
        # Explicit warning: arbitrary Python executed by terminal can still write
        # outside the project's logical permissions (OS sandbox is not implemented).

    def test_web_search_requires_desktop(self):
        sp.register_project(self.conf,'test',self.a)
        with self.assertRaises(PermissionError):
            sm.do_task(self.conf,{'version':1,'project':'test','action':'web_search','query':'Recife'},
                       approval_callback=lambda _:True)
        sp.set_permissions(self.conf,'test','read,desktop')
        with patch.object(sm.subprocess,'Popen') as popen:
            sm.do_task(self.conf,{'version':1,'project':'test','action':'web_search','query':'Recife'},
                       approval_callback=lambda _:True)
        popen.assert_called_once()

    def test_registration_does_not_overwrite_existing(self):
        sp.register_project(self.conf,'test',self.a)
        with self.assertRaisesRegex(ValueError,'já cadastrado'):
            sp.register_project(self.conf,'test',self.b)
        self.assertEqual(self.conf['projects']['test']['path'],str(self.a))

    def test_replace_keeps_permissions(self):
        sp.register_project(self.conf,'test',self.a)
        sp.set_permissions(self.conf,'test','read,write')
        sp.register_project(self.conf,'test',self.b,replace=True)
        self.assertEqual(self.conf['projects']['test']['path'],str(self.b))
        self.assertTrue(sp.permissions_for(self.conf['projects']['test'])['write'])

    def test_remove_only_registration(self):
        sp.register_project(self.conf,'test',self.a)
        sp.remove_project(self.conf,'test')
        self.assertTrue((self.a/'test.txt').exists())
        self.assertEqual(self.conf['projects'],{})

    def test_reject_home_or_root_access(self):
        for path in (Path.home(), Path('/')):
            with self.subTest(path=path), self.assertRaises(ValueError):
                sp.register_project(self.conf,'test',path)

    def test_reject_invalid_permissions_and_names(self):
        for names in ('read,admin','read,execute','read,*'):
            with self.subTest(names=names), self.assertRaises(ValueError):
                sp.parse_permissions(names)
        for name in ('../x','x/y','.hidden','x y'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                sp.register_project(self.conf,name,self.a)

    def test_disallow_malformed_permission_types(self):
        project = {'permissions':{'write':'true'}}
        with self.assertRaises(ValueError):
            sp.permissions_for(project)

    def test_unknown_action_denied(self):
        sp.register_project(self.conf,'test',self.a)
        with self.assertRaises(ValueError):
            sm.do_task(self.conf,{'version':1,'project':'test','action':'unknown'})

    def test_project_isolation(self):
        sp.register_project(self.conf,'a',self.a)
        sp.register_project(self.conf,'b',self.b)
        sp.set_permissions(self.conf,'a','read,write')
        with self.assertRaises(PermissionError):
            sp.check_permission(self.conf,'b','write')

    def test_service_reloads_permissions_every_cycle(self):
        sp.register_project(self.conf,'test',self.a)
        first = self.conf
        second = {'control_repo':'owner/private','projects':{
            'test':{'path':str(self.a), 'permissions':{'read':True,'write':True,
                       'terminal':False,'desktop':False,'environment':False}}
        }}
        with patch.object(sm,'load_config',return_value=second) as read, \
             patch.object(sm,'process_once',return_value=0) as process:
            sm.serve_tasks(first,object(),once=True,reload_config=True)
        read.assert_called_once()
        self.assertIs(process.call_args.args[0],second)

    def test_service_detects_control_repo_switch(self):
        sp.register_project(self.conf,'test',self.a)
        switched = {'control_repo':'other/private','projects':{}}
        with patch.object(sm,'load_config',return_value=switched), \
             patch.object(sm,'process_once') as process, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'Canal de controle alterado'):
                sm.serve_tasks(self.conf,object(),once=True,reload_config=True)
        process.assert_not_called()

    def test_cli_projects_prints_expected(self):
        sp.register_project(self.conf,'test',self.a)
        buffer=io.StringIO()
        with patch.object(sm,'load_config',return_value=self.conf), \
             patch.object(sys,'argv',['solo_mcp.py','projects']), \
             contextlib.redirect_stdout(buffer):
            sm.cli()
        self.assertIn('test:',buffer.getvalue())
        self.assertIn('permite=read',buffer.getvalue())

    def test_cli_set_permissions_writes_private_config(self):
        sp.register_project(self.conf,'test',self.a)
        with patch.object(sm,'load_config',return_value=self.conf), \
             patch.object(sm,'save_config') as save, \
             patch.object(sys,'argv',['solo_mcp.py','set-permissions','--project','test',
                                      '--allow','read,desktop']), \
             contextlib.redirect_stdout(io.StringIO()):
            sm.cli()
        save.assert_called_once()
        self.assertEqual(self.conf['projects']['test']['permissions']['desktop'],True)
        self.assertEqual(self.conf['projects']['test']['permissions']['terminal'],False)


if __name__=='__main__':
    unittest.main()
