"""Functional contracts for the new local desktop bridge and lifecycle."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import launch
import solo_desktop
import solo_mcp as sm
import solo_ui
import solo_workspaces as ws


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.folder=self.root/'project';self.folder.mkdir()
        for obj,name,value in [(sm,'CONFIG_PATH',self.root/'config.json'),(ws,'CONTEXT_ROOT',self.root/'contexts')]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        self.backend=solo_ui.AppBackend()

    def wait_job(self):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            job=self.backend.job_status()
            if job and job['status']!='running':return job
            time.sleep(.01)
        self.fail('Job did not finish')

    def test_local_first_does_not_need_github(self):
        with patch.object(sm,'gh_token',side_effect=AssertionError('No auth expected')):
            self.backend.dispatch('create_workspace',{'name':'primeiro','folder':str(self.folder)})
            self.backend.dispatch('save_context',{'name':'primeiro','content':'Decisões locais.'})
            details=self.backend.dispatch('workspace',{'name':'primeiro'})
        self.assertEqual(details['context'],'Decisões locais.')
        self.assertFalse(details['context_shared'])
        self.assertEqual(self.backend.load()['active_workspace'],'primeiro')
        self.assertNotIn('control_repo',self.backend.load())

    def test_name_limit_and_invalid_characters(self):
        for name in ('a'*51,'nome com espaço','acentuação','../bad','_bad',''):
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'50 caracteres'):
                self.backend.create_workspace(name,str(self.folder))
        self.backend.create_workspace('a'*50,str(self.folder))

    def test_context_byte_limit_with_unicode_is_enforced(self):
        self.backend.create_workspace('test',str(self.folder))
        self.backend.save_workspace_context('test','á'*8000)
        with self.assertRaises(ValueError):self.backend.save_workspace_context('test','á'*8001)
        self.assertEqual(self.backend.read_context('test'),'á'*8000)

    def test_share_missing_context_has_actionable_gui_error(self):
        self.backend.create_workspace('test',str(self.folder))
        with self.assertRaisesRegex(ValueError,'Salve o contexto'):
            self.backend.set_sharing('test',True)
        with self.assertRaises(ValueError):self.backend.set_sharing('test','true')

    def test_missing_project_folder_does_not_break_context_or_unregister(self):
        self.backend.create_workspace('test',str(self.folder))
        self.backend.save_workspace_context('test','Persistente')
        self.folder.rmdir()
        detail=self.backend.workspace('test')
        self.assertFalse(detail['git']['is_repo'])
        self.assertEqual(detail['context'],'Persistente')
        self.backend.remove('test')
        self.assertEqual(ws.context_path('test').read_text(),'Persistente')

    def test_unknown_native_methods_are_rejected(self):
        for method in ('load','__class__','eval','run','write_file'):
            with self.subTest(method=method),self.assertRaises(ValueError):
                self.backend.dispatch(method,{})

    def test_job_progress_and_duplicate_prevention(self):
        release=threading.Event()
        def operation(progress):
            progress('Baixando');release.wait(3);return {'ready':True}
        first=self.backend.start_job('Preparar',operation)
        with self.assertRaisesRegex(ValueError,'andamento'):
            self.backend.start_job('Duplicado',operation)
        release.set();job=self.wait_job()
        self.assertEqual(job['id'],first['job_id'])
        self.assertEqual(job['lines'],['Baixando'])
        self.assertEqual(job['result'],{'ready':True})

    def test_failed_job_reports_failure_not_success(self):
        def fail(progress):raise RuntimeError('Download interrompido')
        self.backend.start_job('Preparar',fail)
        job=self.wait_job()
        self.assertEqual(job['status'],'error')
        self.assertEqual(job['error'],'Download interrompido')

    def test_connect_preserves_projects_and_verifies_private(self):
        self.backend.create_workspace('test',str(self.folder))
        with patch.object(sm,'gh_token',return_value='not-a-real-token'),patch.object(sm,'require_private_repo',return_value={'private':True}):
            self.backend.connect('owner/private');job=self.wait_job()
        self.assertEqual(job['status'],'done')
        self.assertEqual(self.backend.load()['control_repo'],'owner/private')
        self.assertIn('test',self.backend.load()['projects'])
        self.assertNotIn('token',sm.CONFIG_PATH.read_text())

    def test_public_repo_rejection_does_not_change_existing_config(self):
        sm.save_config({'control_repo':'owner/old','projects':{}})
        with patch.object(sm,'gh_token',return_value='test'),patch.object(sm,'require_private_repo',side_effect=RuntimeError('Repositório público')):
            self.backend.connect('owner/public');job=self.wait_job()
        self.assertEqual(job['status'],'error')
        self.assertEqual(self.backend.load()['control_repo'],'owner/old')

    def test_switch_control_requires_pausing_active_service(self):
        sm.save_config({'control_repo':'owner/old','projects':{}})
        with patch.object(sm,'gh_token',return_value='test'),patch.object(sm,'require_private_repo',return_value={}),patch.object(self.backend,'tool_status',return_value={'service':'active'}):
            self.backend.connect('owner/new');job=self.wait_job()
        self.assertEqual(job['status'],'error')
        self.assertEqual(self.backend.load()['control_repo'],'owner/old')

    def test_existing_active_service_repair_is_non_destructive(self):
        """Downloaded UI must not replace the working installed unit or its backup."""
        unit=self.root/'solo-mcp.service'
        backup=self.root/'solo-mcp.service.bak'
        unit.write_text('[Unit]\nDescription=Solo-MCP - ponte de tarefas GitHub\n'
                        '[Service]\nExecStart=/usr/bin/python3 /home/user/Solo-MCP/solo_mcp.py serve --background\n')
        backup.write_text('historical backup')
        sm.save_config({'control_repo':'owner/private','projects':{}})
        with patch.object(sm,'SERVICE_FILE',unit), \
             patch.object(self.backend,'tool_status',return_value={'service':'active'}), \
             patch.object(self.backend,'github_client',side_effect=AssertionError('No remote required')), \
             patch.object(solo_ui.subprocess,'run',side_effect=AssertionError('No subprocess allowed')):
            self.backend.service('repair')
            result=self.wait_job()
        self.assertEqual(result['status'],'done')
        self.assertEqual(result['result'],'active')
        self.assertIn('não alterei', ' '.join(result['lines']).lower())
        self.assertEqual(backup.read_text(),'historical backup')
        self.assertIn('/home/user/Solo-MCP',unit.read_text())

    def test_inactive_service_in_other_install_is_not_replaced(self):
        unit=self.root/'solo-mcp.service'
        unit.write_text('[Unit]\nDescription=Solo-MCP - ponte de tarefas GitHub\n')
        sm.save_config({'control_repo':'owner/private','projects':{}})
        with patch.object(sm,'SERVICE_FILE',unit), \
             patch.object(self.backend,'tool_status',return_value={'service':'inactive'}), \
             patch.object(solo_ui.subprocess,'run',side_effect=AssertionError('No subprocess allowed')):
            self.backend.service('repair')
            result=self.wait_job()
        self.assertEqual(result['status'],'error')
        self.assertIn('outra pasta',result['error'])

    def test_existing_matching_active_service_does_not_restart(self):
        unit=self.root/'solo-mcp.service'
        unit.write_text(sm.generate_user_unit())
        sm.save_config({'control_repo':'owner/private','projects':{}})
        with patch.object(sm,'SERVICE_FILE',unit), \
             patch.object(self.backend,'tool_status',return_value={'service':'active'}), \
             patch.object(solo_ui.subprocess,'run',side_effect=AssertionError('No subprocess allowed')):
            self.backend.service('repair')
            result=self.wait_job()
        self.assertEqual(result['status'],'done')
        self.assertIn('Nenhum reparo', ' '.join(result['lines']))

    def test_new_approvals_are_notified_once_only(self):
        sm.save_config({'control_repo':'owner/private','projects':{}})
        self.backend.on_pending=lambda count: notified.append(count)
        notified=[]
        first=[{'number':27,'digest':'a','task':{'action':'run'}}]
        extra=[*first,{'number':28,'digest':'b','task':{'action':'run'}}]
        with patch.object(self.backend,'github_client',return_value=object()), \
             patch.object(solo_desktop,'pending_details',side_effect=[first,first,extra,extra]):
            for _ in range(4):
                self.backend.approvals()
        self.assertEqual(notified,[1,1])
        self.assertEqual({x['number'] for x in self.backend.pending},{27,28})

    def test_decision_requires_the_loaded_preview(self):
        sm.save_config({'control_repo':'owner/private','projects':{}})
        self.backend.pending_repo='owner/private'
        with patch.object(solo_desktop,'decide') as decide:
            with self.assertRaises(ValueError):self.backend.decision(1,'forged',True)
            decide.assert_not_called()

    def test_decision_cannot_cross_repositories(self):
        sm.save_config({'control_repo':'owner/new','projects':{}})
        self.backend.pending_repo='owner/old'
        self.backend.pending=[{'number':1,'digest':'known','task':{}}]
        with self.assertRaisesRegex(ValueError,'conexão mudou'):
            self.backend.decision(1,'known',True)

    def test_execution_failure_is_a_failed_job(self):
        sm.save_config({'control_repo':'owner/private','projects':{}})
        self.backend.pending_repo='owner/private'
        self.backend.pending=[{'number':1,'digest':'known','task':{}}]
        with patch.object(sm,'gh_token',return_value='test'),patch.object(solo_desktop,'decide',return_value={'ok':False,'error':'Sem permissão'}):
            self.backend.decision(1,'known',True);job=self.wait_job()
        self.assertEqual(job['status'],'error')
        self.assertEqual(job['error'],'Sem permissão')

    def test_optional_installer_is_fixed_and_requires_supported_os(self):
        with self.assertRaises(ValueError):self.backend.install_tool('arbitrary-package')
        with patch.object(self.backend,'tool_status',return_value={'system_installer':False}):
            with self.assertRaisesRegex(ValueError,'Debian/Ubuntu'):self.backend.install_tool('podman')
        with patch.object(self.backend,'tool_status',return_value={'system_installer':True}),patch.object(solo_ui.shutil,'which',return_value='/usr/bin/pkexec'),patch.object(solo_ui.solo_kit,'_run') as run:
            self.backend.install_tool('podman');job=self.wait_job()
        self.assertEqual(job['status'],'done')
        run.assert_called_once_with(['/usr/bin/pkexec','/usr/bin/apt-get','install','-y','podman'],timeout=600)

    def test_launcher_is_terminal_free_and_can_handle_spaces(self):
        with patch.object(launch,'ROOT',self.root/'some space'):
            content=launch.desktop_entry()
        self.assertIn('Terminal=false',content)
        self.assertIn('some space/launch.py"',content)
        self.assertNotIn('tkinter',content)
        self.assertNotIn('sh -c',content)
        with self.assertRaises(ValueError):launch.desktop_quote('/tmp/unsafe\nExec=bad')

    def test_legacy_autostart_can_be_migrated(self):
        with patch.dict(os.environ,{'XDG_CONFIG_HOME':str(self.root)}):
            path=solo_desktop.autostart_path();path.parent.mkdir()
            path.write_text('[Desktop Entry]\nName=Solo-MCP Aprovações\nExec=python3 solo_mcp.py desktop\n')
            solo_desktop.manage_autostart('install')
            self.assertIn('launch.py',path.read_text())
            self.assertIn('Terminal=false',path.read_text())

    def test_native_status_distinguishes_wayland_from_missing_tools(self):
        with patch.dict(os.environ,{'XDG_SESSION_TYPE':'wayland','DISPLAY':':1'}),patch.object(solo_ui.solo_kit.shutil,'which',return_value='/usr/bin/tool'):
            kit=solo_ui.solo_kit.status()
            missing=solo_ui.solo_kit.native_missing()
        self.assertFalse(kit['native_ready'])
        self.assertEqual(missing,[])


@unittest.skipUnless(os.environ.get('SOLO_MCP_GUI_TESTS')=='1','Native WebKit smoke is opt-in')
class NativeWebKitSmoke(unittest.TestCase):
    def test_real_native_bridge_and_editor(self):
        import gi
        gi.require_version('Gtk','3.0');gi.require_version('WebKit2','4.1')
        from gi.repository import GLib,WebKit2
        from solo_app import create_application
        from tools.preview import PreviewBackend
        with tempfile.TemporaryDirectory() as temp,patch.object(sm,'CONFIG_PATH',Path(temp)/'config.json'),patch.object(ws,'CONTEXT_ROOT',Path(temp)/'contexts'):
            folder=Path(temp)/'native-project';folder.mkdir()
            backend=PreviewBackend()
            # Test the actual native bridge with local real mutations.
            app=create_application(backend=backend,application_id='io.github.solo_mcp.Smoke')
            outcome={};started=[False];injected=[False];query_pending=[False];timed_out=[False]
            script=r'''
(async()=>{
 const wait=async(fn)=>{for(let i=0;i<150;i++){if(fn())return;await new Promise(r=>setTimeout(r,30));}throw Error('UI wait timed out: '+String(fn));};
 const assert=(value,message)=>{if(!value)throw Error(message);};
 await wait(()=>state.data);
 document.querySelector('[data-action="create"]').click();
 await wait(()=>document.querySelector('#workspace-name'));
 const input=document.querySelector('#workspace-name');input.value='a'.repeat(51);input.dispatchEvent(new Event('input',{bubbles:true}));
 assert(document.querySelector('#name-count').classList.contains('invalid'),'Counter must turn red');
 assert(document.querySelector('#modal-submit').disabled,'Oversize name must block submit');
 input.value='native-test';input.dispatchEvent(new Event('input',{bubbles:true}));
 document.querySelector('#workspace-folder').value=FOLDER;
 document.querySelector('#workspace-folder').dispatchEvent(new Event('input',{bubbles:true}));
 document.querySelector('#modal-submit').click();
 await wait(()=>state.name==='native-test'&&state.detail);
 document.querySelector('[data-tab="context"]').click();
 await wait(()=>document.querySelector('#context-editor'));
 const editor=document.querySelector('#context-editor');editor.value='# Memória\n\nSalvo pela janela WebKit real.';editor.dispatchEvent(new Event('input',{bubbles:true}));
 document.querySelector('#save-context').click();
 await wait(()=>document.querySelector('#save-status').textContent.startsWith('Salvo no computador às'));
 assert(!state.dirty,'Save must clear dirty state');
 editor.value+='\nRascunho não salvo';editor.dispatchEvent(new Event('input',{bubbles:true}));
 document.querySelector('[data-page="home"]').click();
 await wait(()=>document.querySelector('#dialog').open);
 assert(document.querySelector('#dialog-title').textContent==='Descartar alterações?','Unsaved guard missing');
 document.querySelector('[data-action="close-modal"]').click();
 assert(state.dirty,'Cancel must retain draft');
 await wait(()=>!document.querySelector('[data-page="home"]').disabled);
 document.querySelector('[data-page="home"]').click();
 await wait(()=>document.querySelector('#dialog').open);
 document.querySelector('#modal-submit').click();
 await wait(()=>state.page==='home'&&!document.querySelector('#dialog').open);
 window.__smoke={ok:true,title:document.querySelector('h1').textContent};
})().catch(error=>window.__smoke={error:String(error),stack:error.stack,body:document.body.innerText.slice(-1500)});
'''.replace('FOLDER',json.dumps(str(folder)))
            def inject_once(view=None,event=None):
                # The Xvfb WebKit process may finish loading before the first
                # GLib timer tick. Do not rely only on a late load-changed hook.
                if injected[0] or not app.view:
                    return
                if event is not None and event != WebKit2.LoadEvent.FINISHED:
                    return
                if app.view.get_estimated_load_progress() < 0.999:
                    return
                injected[0]=True
                app.evaluate(script)

            def poll_result():
                if not app.window:return True
                if not started[0]:
                    started[0]=True
                    app.view.connect('load-changed',inject_once)
                inject_once()
                if not injected[0] or query_pending[0]:return not bool(outcome)
                query_pending[0]=True
                def checked(view,result,*_):
                    query_pending[0]=False
                    try:
                        raw=view.evaluate_javascript_finish(result).to_string()
                        value=json.loads(raw)
                        if value:
                            outcome.update(value)
                            app.closed=True;app.window.destroy();app.quit()
                    except Exception as exc:
                        outcome['error']=str(exc);app.quit()
                app.view.evaluate_javascript('JSON.stringify(window.__smoke || null)',-1,None,None,None,checked,None)
                return not bool(outcome)
            GLib.timeout_add(80,poll_result)
            def timeout():
                timed_out[0]=True
                if not outcome:
                    details={'injected':injected[0]}
                    if app.view:
                        details['uri']=app.view.get_uri()
                        details['progress']=app.view.get_estimated_load_progress()
                    outcome['error']='Native UI timed out: '+repr(details)
                    app.quit()
                return False
            timeout_id=GLib.timeout_add_seconds(75,timeout)
            app.run(['solo-native-smoke'])
            if not timed_out[0]:GLib.source_remove(timeout_id)
            self.assertTrue(outcome.get('ok'),outcome)
            self.assertEqual(backend.read_context('native-test'),'# Memória\n\nSalvo pela janela WebKit real.')
            self.assertFalse(backend.details('native-test')['context_shared'])


if __name__=='__main__':unittest.main()
