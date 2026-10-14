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
                            'digest':fingerprint(task)})
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
    if allow:
        try:
            result = {'ok':True,'result':sm.do_task(config,task,approval_callback=lambda _:True)}
        except Exception as exc:
            result = {'ok':False,'error':str(exc)[:800]}
    else:
        result = {'ok':True,'result':{'status':'rejected'}}
    fence = chr(96)*3
    body = sm.RESULT_MARKER + '\n' + fence+'json\n'+json.dumps(result,ensure_ascii=False,indent=2)[:50000]+'\n'+fence
    gh.request('POST',issue_path+'/comments',{'body':body})
    gh.request('PATCH',issue_path,{'state':'closed'})
    return result


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
    def esc(value):
        value = str(Path(value).resolve())
        return '"' + value.replace('\\','\\\\').replace('"','\\"').replace('%','%%') + '"'
    content = ('[Desktop Entry]\nType=Application\nName=Solo-MCP Aprovações\n'
               'Terminal=false\nStartupNotify=false\nExec='+esc(sys.executable)+' '+
               esc(Path(__file__).parent/'solo_mcp.py')+' desktop\n')
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.exists() and path.read_text(encoding='utf-8') != content:
        raise RuntimeError('Autostart diferente já existe em '+str(path))
    path.write_text(content,encoding='utf-8')
    path.chmod(0o600)
    print('Autostart instalado; execute agora python3 solo_mcp.py desktop')


class Panel:
    def __init__(self,tk,ttk,root,config,gh):
        self.tk,self.root,self.config,self.gh=tk,root,config,gh
        self.events=queue.Queue()
        self.stop=threading.Event()
        self.refresh=threading.Event()
        self.entries=[]
        self.busy=False
        self.seen=set()
        root.title('Solo-MCP - Aprovações')
        width,height=460,440
        root.geometry(f'{width}x{height}+{max(0,root.winfo_screenwidth()-width-25)}+40')
        root.attributes('-topmost',True)
        root.minsize(360,340)
        root.protocol('WM_DELETE_WINDOW',self.close)
        frame=ttk.Frame(root,padding=12)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Solo-MCP · Aprovações',font=('Sans',13,'bold')).pack(anchor='w')
        self.label=ttk.Label(frame,text='Conectando...')
        self.label.pack(anchor='w',pady=(3,8))
        self.items=tk.Listbox(frame,height=5,exportselection=False)
        self.items.pack(fill='x')
        self.items.bind('<<ListboxSelect>>',self.on_selection)
        ttk.Label(frame,text='Prévia completa:').pack(anchor='w',pady=(8,3))
        detail=ttk.Frame(frame)
        detail.pack(fill='both',expand=True)
        self.preview=tk.Text(detail,height=10,wrap='word',state='disabled')
        self.preview.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(detail,orient='vertical',command=self.preview.yview)
        scroll.pack(side='right',fill='y')
        self.preview.configure(yscrollcommand=scroll.set)
        bar=ttk.Frame(frame)
        bar.pack(fill='x',pady=(9,0))
        self.allow=ttk.Button(bar,text='Autorizar',command=lambda:self.choose(True))
        self.allow.pack(side='left')
        self.deny=ttk.Button(bar,text='Recusar',command=lambda:self.choose(False))
        self.deny.pack(side='left',padx=8)
        ttk.Button(bar,text='Atualizar',command=self.refresh.set).pack(side='right')
        self.set_preview('Aguardando solicitações...')
        self.update_buttons()
        threading.Thread(target=self.poll,daemon=True).start()
        root.after(250,self.handle_events)

    def set_preview(self,text):
        self.preview.config(state='normal')
        self.preview.delete('1.0','end')
        self.preview.insert('1.0',text)
        self.preview.config(state='disabled')

    def selected(self):
        sel=self.items.curselection()
        return self.entries[sel[0]] if sel else None

    def update_buttons(self):
        state='normal' if self.selected() and not self.busy else 'disabled'
        self.allow.config(state=state)
        self.deny.config(state=state)

    def on_selection(self,_event=None):
        item=self.selected()
        self.set_preview(json.dumps(item['task'],indent=2,ensure_ascii=False) if item else 'Selecione uma tarefa.')
        self.update_buttons()

    def poll(self):
        while not self.stop.is_set():
            try:self.events.put(('tasks',pending_details(self.config,self.gh)))
            except Exception as exc:self.events.put(('error',str(exc)))
            self.refresh.wait(10)
            self.refresh.clear()

    def handle_events(self):
        from tkinter import messagebox
        while True:
            try:kind,data=self.events.get_nowait()
            except queue.Empty:break
            if kind=='tasks':
                ids={entry['number'] for entry in data}
                if ids-self.seen:
                    try:subprocess.Popen(['notify-send','Solo-MCP','Nova tarefa aguardando decisão'],
                                         stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    except OSError:pass
                self.seen=ids
                old=self.selected()
                old_id=old['number'] if old else None
                self.entries=data
                self.items.delete(0,'end')
                for entry in data:
                    task=entry['task']
                    self.items.insert('end',f"#{entry['number']} · {(task.get('workspace') or task.get('project'))} · {task.get('action')}")
                for i,entry in enumerate(data):
                    if entry['number']==old_id:self.items.selection_set(i)
                self.label.config(text=f'{len(data)} tarefa(s) aguardando aprovação')
                self.on_selection()
            elif kind=='error':
                self.label.config(text='Falha na consulta: '+data[:100])
            elif kind=='done':
                self.busy=False
                if isinstance(data,Exception):
                    messagebox.showerror('Solo-MCP',str(data)[:900],parent=self.root)
                else:
                    messagebox.showinfo('Solo-MCP',json.dumps(data,ensure_ascii=False,indent=2)[:1000],parent=self.root)
                self.refresh.set()
                self.update_buttons()
        if not self.stop.is_set():self.root.after(250,self.handle_events)

    def choose(self,allow):
        from tkinter import messagebox
        item=self.selected()
        if item is None or self.busy:return
        op='Autorizar' if allow else 'Recusar'
        task=item['task']
        description=f"Issue #{item['number']}\nProjeto: {(task.get('workspace') or task.get('project'))}\nAção: {task.get('action')}"
        if not messagebox.askyesno('Solo-MCP',f'{op} esta tarefa?\n\n{description}\nRevise a prévia antes de confirmar.',parent=self.root):
            return
        self.busy=True
        self.update_buttons()
        threading.Thread(target=self.act,args=(item['number'],item['digest'],allow),daemon=True).start()

    def act(self,number,digest,allow):
        try:
            current = sm.load_config()
            if current['control_repo'] != self.config['control_repo']:
                raise RuntimeError('Reinicie o painel: repositório de controle alterado')
            self.events.put(('done',decide(current,self.gh,number,digest,allow)))
        except Exception as exc:self.events.put(('done',exc))

    def close(self):
        self.stop.set()
        self.refresh.set()
        self.root.destroy()


def start_desktop():
    if sys.platform!='linux':
        raise RuntimeError('Janela gráfica suportada apenas no Linux')
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as exc:
        raise RuntimeError('Tkinter ausente. No Ubuntu instale python3-tk') from exc
    config=sm.load_config()
    gh=sm.Github(sm.gh_token())
    sm.require_private_repo(gh,config['control_repo'])
    try:root=tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError('Abra na sessão gráfica do usuário') from exc
    Panel(tk,ttk,root,config,gh)
    root.mainloop()
