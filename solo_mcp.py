#!/usr/bin/env python3
"""Solo-MCP: local, approval-gated GitHub Issues bridge (standard library only).

This is a GitHub-Issues transport MVP, not an MCP protocol server.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

CONFIG_PATH = Path.home() / '.config' / 'solo-mcp' / 'config.json'
MARKER = 'SOLO_MCP_TASK_V1'
RESULT_MARKER = 'SOLO_MCP_RESULT_V1'
READ_LIMIT = 20000
OUTPUT_LIMIT = 20000
BLOCKED_NAMES = {'.env', '.npmrc', '.pypirc', 'id_rsa', 'id_ed25519', 'credentials', 'credentials.json', 'secrets.json', 'known_hosts'}
BLOCKED_PARTS = {'.ssh', '.gnupg', '.aws', '.git', '.config', '.kube', 'node_modules'}
ALLOWED_TOOLS = {'python', 'python3', 'pytest', 'git', 'javap', 'java', 'jar', 'unzip', 'zipinfo', 'ls', 'find', 'grep', 'rg', 'head', 'tail', 'file', 'stat', 'strings', 'jadx', 'usb-devices', 'lsusb'}


def save_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix='.config-', dir=CONFIG_PATH.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(config, out, ensure_ascii=False, indent=2)
            out.write('\n')
        os.chmod(temp, 0o600)
        os.replace(temp, CONFIG_PATH)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def load_config():
    if not CONFIG_PATH.is_file():
        raise RuntimeError('Configuração inexistente. Use: python3 solo_mcp.py init --control DONO/REPO_PRIVADO')
    config = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    control = config.get('control_repo', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', control):
        raise RuntimeError('control_repo inválido')
    return config


def gh_token():
    token = os.environ.get('SOLO_MCP_TOKEN', '').strip()
    if token:
        return token
    try:
        result = subprocess.run(['gh', 'auth', 'token'], text=True, capture_output=True, timeout=8, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError('Autentique com gh auth login ou defina SOLO_MCP_TOKEN no ambiente')


class Github:
    def __init__(self, token):
        self.token = token

    def request(self, method, endpoint, data=None):
        if not endpoint.startswith('/repos/'):
            raise ValueError('Somente endpoints /repos/... são permitidos')
        url = 'https://api.github.com' + endpoint
        body = json.dumps(data).encode('utf-8') if data is not None else None
        req = urllib.request.Request(url, data=body, method=method, headers={
            'Authorization': 'Bearer ' + self.token,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'solo-mcp-bridge/0.1',
            'Content-Type': 'application/json',
        })
        try:
            with urllib.request.urlopen(req, timeout=25) as res:
                data = res.read(1024 * 1024)
                return json.loads(data) if data else None
        except urllib.error.HTTPError as ex:
            msg = ex.read(500).decode('utf-8', errors='replace')
            raise RuntimeError(f'GitHub HTTP {ex.code}: {msg}') from ex


def require_private_repo(gh, repo):
    info = gh.request('GET', '/repos/' + repo)
    if not info.get('private', False):
        raise RuntimeError('O repositório de CONTROLE precisa ser PRIVADO. Não publique tarefas em repositórios públicos.')
    return info


def resolve_project(config, project):
    projects = config.get('projects', {})
    if project not in projects:
        raise ValueError('Projeto não cadastrado: ' + str(project))
    root = Path(projects[project]['path']).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Raiz de projeto não é um diretório')
    return root


def safe_path(root, relative, write=False):
    if not isinstance(relative, str) or not relative or '\x00' in relative:
        raise ValueError('Caminho inválido')
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('Caminho absoluto ou traversal bloqueado')
    if any(p in BLOCKED_PARTS or p in BLOCKED_NAMES or p.startswith('.env.') or p.endswith(('.pem', '.key', '.p12', '.pfx')) for p in rel.parts):
        raise ValueError('Caminho protegido')
    target = (root / rel).resolve(strict=False)
    if not target.is_relative_to(root):
        raise ValueError('Caminho fora da raiz do projeto')
    if write and target.is_symlink():
        raise ValueError('Symlink bloqueado para escrita')
    return target


def approve(description):
    print('\n[APROVAÇÃO LOCAL NECESSÁRIA]')
    print(description[:2500])
    response = input('Autorizar esta operação? [s/N]: ').strip().casefold()
    approved = response == 's'
    print('Operação autorizada.' if approved else 'Operação cancelada.')
    return approved


def do_task(config, task):
    if not isinstance(task, dict) or task.get('version') != 1:
        raise ValueError('Formato de tarefa inválido')
    action = task.get('action')
    root = resolve_project(config, task.get('project'))
    if action == 'list':
        path = safe_path(root, task.get('path', '.'))
        if not path.is_dir():
            raise ValueError('Não é um diretório')
        entries = []
        for p in sorted(path.iterdir(), key=lambda x: x.name.lower())[:100]:
            try:
                safe_path(root, str(p.relative_to(root)))
            except ValueError:
                continue
            entries.append({'name': p.name, 'kind': 'dir' if p.is_dir() else 'file'})
        return {'entries': entries, 'truncated': len(list(path.iterdir())) > 100}
    if action == 'read':
        path = safe_path(root, task.get('path'))
        if not path.is_file():
            raise ValueError('Arquivo não encontrado')
        with path.open('rb') as file:
            blob = file.read(READ_LIMIT + 1)
        if b'\x00' in blob:
            raise ValueError('Arquivo binário: use archive_list ou ferramenta local')
        return {'path': str(path.relative_to(root)), 'content': blob[:READ_LIMIT].decode('utf-8', 'replace'), 'truncated': len(blob) > READ_LIMIT}
    if action == 'archive_list':
        path = safe_path(root, task.get('path'))
        if not zipfile.is_zipfile(path):
            raise ValueError('Não é ZIP/JAR/AAR válido')
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()[:100]
            return {'entries': [{'name': i.filename[:250], 'bytes': i.file_size} for i in infos], 'truncated': len(z.infolist()) > 100}
    if action == 'git_status':
        run = subprocess.run(['git', '-C', str(root), 'status', '--short', '--branch'], text=True, capture_output=True, timeout=20)
        return {'returncode': run.returncode, 'stdout': run.stdout[:OUTPUT_LIMIT], 'stderr': run.stderr[:OUTPUT_LIMIT]}
    if action == 'write':
        content = task.get('content')
        if not isinstance(content, str) or len(content.encode('utf-8')) > 32000:
            raise ValueError('Escrita limitada a 32 KB de texto')
        path = safe_path(root, task.get('path'), write=True)
        if not path.parent.is_dir():
            raise ValueError('Pasta de destino inexistente')
        if path.exists() and not path.is_file():
            raise ValueError('Destino não é arquivo regular')
        current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        if current != task.get('expected_sha256', None):
            raise ValueError('expected_sha256 não confere (proteção contra sobrescrita)')
        if not approve(f'Gravar {path} ({len(content.encode("utf-8"))} bytes); SHA anterior: {current}'):
            return {'status': 'rejected'}
        # Recheck before write to avoid changed file since approval.
        now = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        if now != current:
            raise ValueError('Arquivo mudou durante aprovação')
        fd, temp = tempfile.mkstemp(prefix='.solo-mcp-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as out:
                out.write(content)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp): os.unlink(temp)
        return {'status': 'written', 'path': str(path.relative_to(root)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    if action == 'run':
        argv = task.get('argv')
        if not isinstance(argv, list) or not 1 <= len(argv) <= 30 or not all(isinstance(x, str) and 0 < len(x) <= 2000 for x in argv):
            raise ValueError('argv inválido')
        if argv[0] not in ALLOWED_TOOLS:
            raise ValueError('Executável não está na lista permitida')
        if not approve(f'Projeto: {root}\nExecutar sem shell: {json.dumps(argv, ensure_ascii=False)}'):
            return {'status': 'rejected'}
        seconds = min(90, max(1, int(task.get('timeout', 30))))
        try:
            run = subprocess.run(argv, cwd=root, text=True, capture_output=True, timeout=seconds, env={**os.environ, 'PYTHONUNBUFFERED': '1'})
            return {'returncode': run.returncode, 'stdout': run.stdout[:OUTPUT_LIMIT], 'stderr': run.stderr[:OUTPUT_LIMIT]}
        except subprocess.TimeoutExpired:
            return {'status': 'timeout', 'seconds': seconds}
    raise ValueError('Ação desconhecida: ' + str(action))


def parse_task(body):
    if not isinstance(body, str) or not body.startswith(MARKER + '\n'):
        return None
    try:
        task = json.loads(body.split('\n', 1)[1])
    except json.JSONDecodeError:
        return None
    return task if isinstance(task, dict) and task.get('version') == 1 else None


def process_once(config, gh):
    repo = config['control_repo']
    info = require_private_repo(gh, repo)
    owner = info['owner']['login'].lower()
    qs = urllib.parse.urlencode({'state': 'open', 'per_page': 100, 'sort': 'created', 'direction': 'asc'})
    issues = gh.request('GET', '/repos/' + repo + '/issues?' + qs)
    total = 0
    for issue in issues:
        if issue.get('pull_request') or issue.get('user', {}).get('login', '').lower() != owner:
            continue
        task = parse_task(issue.get('body', ''))
        if task is None:
            continue
        number = int(issue['number'])
        path = '/repos/' + repo + '/issues/' + str(number)
        previous = gh.request('GET', path + '/comments?per_page=100')
        if any(c.get('body', '').startswith(RESULT_MARKER) for c in previous):
            gh.request('PATCH', path, {'state': 'closed'})
            continue
        print(f'[TASK #{number}] {task.get("project")} / {task.get("action")}')
        try:
            result = {'ok': True, 'result': do_task(config, task)}
        except Exception as exc:
            result = {'ok': False, 'error': str(exc)[:800]}
        body = RESULT_MARKER + '\n```json\n' + json.dumps(result, ensure_ascii=False, indent=2)[:50000] + '\n```'
        gh.request('POST', path + '/comments', {'body': body})
        gh.request('PATCH', path, {'state': 'closed'})
        total += 1
    return total


def serve_tasks(config, gh, once=False, interval=10):
    """Consulta tarefas continuamente; só imprime quando há trabalho ou erro."""
    while True:
        try:
            total = process_once(config, gh)
            if total:
                print(f'Tarefas executadas: {total}', flush=True)
        except Exception as ex:
            print('Erro na consulta:', ex, file=sys.stderr, flush=True)
            if once:
                raise
        if once:
            return
        time.sleep(max(10, interval))


def cli():
    ap = argparse.ArgumentParser(description='Solo-MCP: ponte local via GitHub Issues privadas')
    sub = ap.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init', help='Configurar repositório de controle PRIVADO')
    init.add_argument('--control', required=True)
    add = sub.add_parser('add-project', help='Cadastrar projeto local')
    add.add_argument('--name', required=True)
    add.add_argument('--path', required=True)
    add.add_argument('--repo', default='')
    run = sub.add_parser('serve', help='Escutar novas tarefas')
    run.add_argument('--once', action='store_true')
    run.add_argument('--interval', type=int, default=10)
    args = ap.parse_args()
    if args.command == 'init':
        if CONFIG_PATH.exists():
            ap.error(f'Configuração já existe: {CONFIG_PATH}')
        save_config({'control_repo': args.control, 'projects': {}})
        print('Configuração local criada:', CONFIG_PATH)
    elif args.command == 'add-project':
        conf = load_config()
        root = Path(args.path).expanduser().resolve(strict=True)
        if not root.is_dir():
            ap.error('Caminho não é diretório')
        conf.setdefault('projects', {})[args.name] = {'path': str(root), 'github': args.repo}
        save_config(conf)
        print(f'Projeto {args.name} registrado: {root}')
    elif args.command == 'serve':
        conf = load_config()
        gh = Github(gh_token())
        require_private_repo(gh, conf['control_repo'])
        print('Ponte conectada a', conf['control_repo'])
        if not args.once:
            print(f'Aguardando tarefas (consulta a cada {max(10, args.interval)}s). Ctrl+C para sair.')
        try:
            serve_tasks(conf, gh, once=args.once, interval=args.interval)
        except KeyboardInterrupt:
            print('\nPonte encerrada.')


if __name__ == '__main__':
    cli()
