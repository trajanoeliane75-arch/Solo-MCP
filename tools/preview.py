#!/usr/bin/env python3
"""Disposable local QA harness. Never serves the user's config or credentials.

All external side effects are unavailable. The production desktop has no HTTP
server. This harness intentionally uses temporary projects for UI interaction.
"""
import argparse
import http.server
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import solo_mcp as sm
import solo_workspaces as ws
from solo_ui import AppBackend

ALLOWED = {'state', 'workspace', 'create_workspace', 'remove_workspace', 'prefer_workspace',
           'save_permissions', 'save_context', 'share_context', 'link_repository',
           'unlink_repository', 'approvals', 'job_status'}

class PreviewBackend(AppBackend):
    def state(self):
        result = super().state()
        result['preview'] = True
        return result

    def tool_status(self):
        return {'service':'inactive','gh':True,'podman':False,'native_missing':[],
                'session':'x11','system_installer':False}

    def kit_status(self):
        return {'ready':False,'native_ready':True,'native':'captura X11 disponível',
                'playwright_version':'1.63.0'}

    def dispatch(self, method, params=None):
        if method not in ALLOWED:
            raise ValueError('Esta prévia usa dados temporários. Abra o aplicativo para executar esta ação.')
        if method == 'approvals':
            return {'items': [], 'connected': False}
        return super().dispatch(method, params)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='solo-ui-preview-') as temp:
        base = Path(temp)
        sm.CONFIG_PATH = base/'config.json'
        ws.CONTEXT_ROOT = base/'contexts'
        for folder in ('meu-projeto','laboratorio'):
            (base/folder).mkdir()
        backend = PreviewBackend()
        backend.create_workspace('meu-projeto',str(base/'meu-projeto'))
        backend.create_workspace('laboratorio',str(base/'laboratorio'))
        backend.save_context('meu-projeto','# Objetivo\n\nConstruir com clareza, um passo de cada vez.\n')
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self,*a,**kw):
                super().__init__(*a,directory=str(ROOT/'ui'),**kw)
            def do_POST(self):
                expected=f'127.0.0.1:{args.port}'
                if self.path!='/api' or self.headers.get('Host')!=expected or self.headers.get('X-Solo-Preview')!='1' or self.headers.get('Origin') not in (None,'http://'+expected):
                    self.send_error(403);return
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if size>100000:raise ValueError('Request too large')
                    request=json.loads(self.rfile.read(size))
                    response={'result':backend.dispatch(request['method'],request.get('params'))}
                except Exception as exc:
                    response={'error':str(exc)}
                payload=json.dumps(response).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            def log_message(self,*a):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
        print(f'Preview: http://127.0.0.1:{args.port}',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:server.server_close()

if __name__=='__main__':main()
