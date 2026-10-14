import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import solo_sandbox as sandbox
import solo_projects as sp
import solo_mcp as sm


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.cfg={'control_repo':'owner/private','projects':{}}
        sp.register_project(self.cfg,'dev',self.root)
        sp.set_permissions(self.cfg,'dev','read,environment')

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_network_access_has_no_project_mount(self):
        cmd=sandbox.build_install_command('dev',self.root,['numpy==2.1.0','pandas>=2'])
        self.assertIn('podman',cmd)
        self.assertEqual(cmd[0:3],['podman','run','--rm'])
        self.assertIn('--pull=never',cmd)
        self.assertIn('--cap-drop=ALL',cmd)
        self.assertIn('--read-only',cmd)
        self.assertIn('--only-binary=:all:',cmd)
        self.assertNotIn('network=none',' '.join(cmd))
        self.assertNotIn(str(self.root),' '.join(cmd))
        self.assertFalse(any('type=bind' in part for part in cmd))
        self.assertTrue(any('type=volume' in part for part in cmd))

    def test_run_is_offline_and_project_read_only(self):
        cmd=sandbox.build_run_command('dev',self.root,['python3','-c','print(1)'])
        self.assertIn('--network=none',cmd)
        self.assertIn('--read-only',cmd)
        self.assertIn('--env=PYTHONPATH=/packages',cmd)
        self.assertTrue(any(str(self.root) in arg and 'readonly=true' in arg for arg in cmd))
        self.assertTrue(any('destination=/packages,readonly=true' in arg for arg in cmd))

    def test_volume_matches_across_stages(self):
        installed=sandbox.build_install_command('dev',self.root,['numpy'])
        runtime=sandbox.build_run_command('dev',self.root,['python3','-V'])
        name=sandbox.package_volume('dev',self.root)
        self.assertIn(name,' '.join(installed))
        self.assertIn(name,' '.join(runtime))

    def test_flag_injection_rejected(self):
        for packages in (['--privileged'],['--index-url=https://evil.test'],['https://evil.test/p.whl'],
                         ['numpy;rm -rf /'],['-e .'],[],['numpy\nsteal']):
            with self.subTest(packages=packages), self.assertRaises(ValueError):
                sandbox.validate_packages(packages)

    def test_invalid_image_rejected(self):
        with self.assertRaises(ValueError):
            sandbox.base_argv('attacker/image:latest')

    def test_reject_executable_not_allowlisted(self):
        for cmd in (['sh','-c','rm -rf /'],['bash'],['curl','url'],[]):
            with self.subTest(cmd=cmd), self.assertRaises(ValueError):
                sandbox.validate_run_command(cmd)

    def test_refuse_host_root(self):
        with patch.object(sandbox.os,'geteuid',return_value=0):
            with self.assertRaisesRegex(RuntimeError,'sem root'):
                sandbox.podman_preflight()

    def test_validate_rootless_mode(self):
        with patch.object(sandbox.os,'geteuid',return_value=1000),\
             patch.object(sandbox.shutil,'which',return_value='/usr/bin/podman'),\
             patch.object(sandbox.subprocess,'run',
                          return_value=subprocess.CompletedProcess([],0,'true\n','')) as run:
            sandbox.podman_preflight()
        self.assertEqual(run.call_args.args[0][:2],['podman','info'])

    def test_do_task_install_requires_capability(self):
        sp.set_permissions(self.cfg,'dev','read')
        with self.assertRaises(PermissionError):
            sm.do_task(self.cfg,{'version':1,'project':'dev','action':'sandbox_install',
                                 'packages':['numpy']},approval_callback=lambda _:True)

    def test_install_dispatch_calls_container_only_after_approval(self):
        task={'version':1,'project':'dev','action':'sandbox_install','packages':['numpy==2.1.0']}
        with patch.object(sandbox,'run_sandbox',return_value={'returncode':0}) as execute:
            out=sm.do_task(self.cfg,task,approval_callback=lambda _:False)
            self.assertEqual(out['status'],'rejected')
            execute.assert_not_called()
        with patch.object(sandbox,'run_sandbox',return_value={'returncode':0}) as execute:
            out=sm.do_task(self.cfg,task,approval_callback=lambda _:True)
            self.assertEqual(out['returncode'],0)
            self.assertNotIn(str(self.root),' '.join(execute.call_args.args[0]))

    def test_sandbox_run_requires_read(self):
        sp.set_permissions(self.cfg,'dev','environment')
        task={'version':1,'project':'dev','action':'sandbox_run','argv':['python3','-V']}
        with self.assertRaises(PermissionError):
            sm.do_task(self.cfg,task,approval_callback=lambda _:True)

    def test_sandbox_exec_uses_network_none(self):
        task={'version':1,'project':'dev','action':'sandbox_run','argv':['python3','-V']}
        with patch.object(sandbox,'run_sandbox',return_value={'returncode':0}) as execute:
            sm.do_task(self.cfg,task,approval_callback=lambda _:True)
            self.assertIn('--network=none',execute.call_args.args[0])


if __name__=='__main__':
    unittest.main()
