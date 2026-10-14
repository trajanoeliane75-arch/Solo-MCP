"""Solo-MCP: persistent graphical approval panel for Linux desktops."""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import urllib.parse

import solo_mcp as sm


def fingerprint(task):
    canonical = json.dumps(task, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def pending_details(config, gh):
    repo = config['control_repo']
    owner = sm.require_private_repo(gh, repo)['owner']['login'].lower()
    query = urllib.parse.urlencode({'state':'open','per_page':100})
    issues = gh.request('GET', '/repos/' + repo + '/issues?' + query)
    pending = []
    for issue in issues:
        if issue.get('pull_request') or issue.get('user',{}).get('login','').lower() != owner:
            continue
        task = sm.parse_task(issue.get('body',''))
        if task is not None and task.get('action') in sm.MUTATING_ACTIONS:
            pending.append({'number':int(issue['number']), 'task':task,
                            'digest':fingerprint(task), 'title':str(issue.get('title') or '')[:180]})
    return sorted(pending, key=lambda entry:entry['number'])


def decide(config, gh, number, digest, allow):
    """Re-fetch the entire task and ensure it matches the user's preview."""
    repo = config['control_repo']
    owner = sm.require_private_repo(gh,repo)['owner']['login'].lower()
    issue_path = '/repos/' + repo + '/issues/' + str(int(number))
    issue = gh.request('GET', issue_path)
    if issue.get('state') != 'open' or issue.get('user',{}).get('login','').lower() != owner:
        raise ValueError('Issue indisponível ou autor não autorizado')
    task = sm.parse_task(issue.get('body',''))
    if task is None or task.get('action') not in sm.MUTATING_ACTIONS or fingerprint(task) != digest:
        raise ValueError('Tarefa mudou após a prévia: atualize e revise novamente')
    comments = gh.request('GET', issue_path+'/comments?per_page=100')
    if any(c.get('body','').startswith(sm.RESULT_MARKER) for c in comments):
        raise ValueError('Tarefa já contém resultado')
    import solo_execution
    result = solo_execution.execute(repo,number,task,
        (lambda: {'ok':True,'result':sm.do_task(config,task,approval_callback=lambda _:True)})
        if allow else (lambda: {'ok':True,'result':{'status':'rejected'}}))
    return solo_execution.deliver(gh,repo,number,result,sm.publish_task_result)


def autostart_path():
    base = Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))
    return base/'autostart'/'solo-mcp-desktop.desktop'


def manage_autostart(action):
    path = autostart_path()
    if action == 'uninstall':
        path.unlink(missing_ok=True)
        print('Inicialização automática removida')
        return
    if action != 'install':
        raise ValueError('Ação desconhecida')
    from launch import desktop_entry
    content = desktop_entry() + 'X-GNOME-Autostart-enabled=true\n'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        previous = path.read_text(encoding='utf-8')
        legacy = 'Name=Solo-MCP Aprovações' in previous and 'solo_mcp.py' in previous
        if previous != content and not legacy:
            raise RuntimeError('Autostart diferente já existe em ' + str(path))
    path.write_text(content, encoding='utf-8')
    path.chmod(0o600)
    print('Inicialização automática do Solo-MCP ativada.')



def start_desktop():
    """Open approvals inside the unified application."""
    from solo_app import main
    main(initial_page="approvals")
