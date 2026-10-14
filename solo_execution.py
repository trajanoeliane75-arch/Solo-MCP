"""Local durable at-most-once execution claims for Solo-MCP.

A recorded STARTED operation is never replayed automatically, even after a
process crash. Reconciliation is intentionally manual when the outcome is
uncertain. Does not promise exactly-once side effects.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

class AlreadyClaimed(RuntimeError):
    """Same issue is in progress or uncertain, or result publication is uncertain."""

class TaskChanged(RuntimeError):
    """The issue body changed since it was claimed."""


def fingerprint(task):
    canonical = json.dumps(task, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _database_path():
    state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local' / 'state')))
    return state / 'solo-mcp' / 'execution.sqlite3'


def _connect():
    path = _database_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError('Registro de execução local inválido')
    if not path.exists():
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass  # Another authorized process initialized the same journal.
        else:
            os.close(fd)
    db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    db.execute('PRAGMA busy_timeout=10000')
    db.execute('PRAGMA synchronous=FULL')
    db.execute('''CREATE TABLE IF NOT EXISTS execution (
        repo TEXT NOT NULL, issue INTEGER NOT NULL, digest TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('started','completed')),
        result TEXT, delivery TEXT NOT NULL DEFAULT 'ready'
          CHECK(delivery IN ('ready','sending','published')),
        created REAL NOT NULL, updated REAL NOT NULL,
        PRIMARY KEY(repo,issue)
    )''')
    return db


def _row(db, repo, number):
    return db.execute('SELECT digest,state,result,delivery FROM execution WHERE repo=? AND issue=?',
                      (repo, number)).fetchone()


def _claim(repo, number, digest):
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = _row(db, repo, number)
        if row:
            if row[0] != digest:
                raise TaskChanged('A tarefa mudou depois de iniciada. Atualize e revise a Issue.')
            if row[1] == 'started':
                raise AlreadyClaimed('Esta tarefa já foi iniciada. O resultado ainda é incerto. Não será executada novamente automaticamente.')
            return False, json.loads(row[2])
        now = time.time()
        db.execute('INSERT INTO execution(repo,issue,digest,state,result,delivery,created,updated) VALUES (?,?,?,?,?,?,?,?)',
                   (repo,number,digest,'started',None,'ready',now,now))
        return True, None


def execute(repo, number, task, callback):
    """Durably claim before effects. Callback exceptions also become stored results."""
    digest = fingerprint(task)
    fresh, cached = _claim(repo, number, digest)
    if not fresh:
        return cached
    try:
        result = callback()
    except Exception as ex:
        result = {'ok':False,'error':str(ex)[:800]}
    # All user-facing results are JSON. If serialization fails, leave STARTED,
    # not an unsafe automatic retry after an unknown outcome.
    value = json.dumps(result, ensure_ascii=False)
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE execution SET state='completed',result=?,updated=? WHERE repo=? AND issue=? AND digest=? AND state='started'",
                   (value,time.time(),repo,number,digest))
        if not db.execute('SELECT changes()').fetchone()[0]:
            raise RuntimeError('Registro de execução inconsistente; verifique antes de repetir')
    return result


def _set_delivery(repo, number, expected, next_state):
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE execution SET delivery=?,updated=? WHERE repo=? AND issue=? AND state=\'completed\' AND delivery=?',
                   (next_state,time.time(),repo,number,expected))
        return bool(db.execute('SELECT changes()').fetchone()[0])


def deliver(gh, repo, number, result, publish):
    """No duplicate POST on concurrent calls or uncertain network outcomes.

    When a POST may have reached GitHub but confirmation is lost, keep SENDING.
    A later call first checks GitHub for the marker, then requires manual
    reconciliation if absent. This is deliberately fail-closed.
    """
    issue_path = '/repos/' + repo + '/issues/' + str(int(number))
    comments = gh.request('GET', issue_path + '/comments?per_page=100')
    if any(str(c.get('body','')).startswith('SOLO_MCP_RESULT_V1') for c in comments):
        gh.request('PATCH', issue_path, {'state':'closed'})
        for src in ('sending','ready'):
            _set_delivery(repo,number,src,'published')
        return result
    with _connect() as db:
        row = _row(db,repo,number)
    if row is None or row[1] != 'completed':
        raise AlreadyClaimed('A execução não foi concluída com resultado persistido.')
    if row[3] == 'sending' or row[3] == 'published':
        raise AlreadyClaimed('A publicação anterior pode ter sido recebida. Confira a Issue antes de reconciliar; não será reenviada automaticamente.')
    if not _set_delivery(repo,number,'ready','sending'):
        raise AlreadyClaimed('Outra solicitação já está publicando esta tarefa.')
    published = publish(gh,issue_path,result)
    _set_delivery(repo,number,'sending','published')
    return published
