import sqlite3, json, os
from pathlib import Path
from app.errors import DomainError


def connection():
    path = Path(os.environ.get('DB_PATH', 'data/records.db')); path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10); db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, decision TEXT NOT NULL DEFAULT "待复核", scope TEXT NOT NULL DEFAULT "default", superseded INTEGER NOT NULL DEFAULT 0, sealed INTEGER NOT NULL DEFAULT 0, sealed_at TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    # 旧库增量加列，不破坏既有批次与原始依据。
    existing = {row['name'] for row in db.execute('PRAGMA table_info(runs)')}
    for column, clause in (('scope', "TEXT NOT NULL DEFAULT 'default'"), ('superseded', 'INTEGER NOT NULL DEFAULT 0'),
                           ('sealed', 'INTEGER NOT NULL DEFAULT 0'), ('sealed_at', 'TEXT')):
        if column not in existing:
            db.execute(f'ALTER TABLE runs ADD COLUMN {column} {clause}')
    return db


def _scope_of(body):
    return str(body.get('manifest', {}).get('parameters', {}).get('period') or 'default')


def save(run_id, body):
    scope = _scope_of(body)
    with connection() as db:
        # INSERT OR IGNORE：同输入重复执行命中同一 run，绝不重复耗用审批额度。
        db.execute('INSERT OR IGNORE INTO runs(id,body,scope) VALUES (?,?,?)',
                   (run_id, json.dumps(body, ensure_ascii=False), scope))
        # 同 scope 的旧批次整份保留，仅标记 superseded；不删除、不覆盖任何证据。
        db.execute('UPDATE runs SET superseded=1 WHERE scope=? AND id<>?', (scope, run_id))
        db.execute("INSERT INTO meta(key,value) VALUES ('latest',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (run_id,))
    return get(run_id)


def get(run_id):
    with connection() as db:
        r = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
    if not r: raise DomainError('NOT_FOUND', '批次不存在', 404)
    body = json.loads(r['body'])
    body.update(run_id=r['id'], review_version=r['version'], decision=r['decision'],
                scope=r['scope'], superseded=bool(r['superseded']), sealed=bool(r['sealed']),
                sealed_at=r['sealed_at'])
    return body


def history():
    with connection() as db:
        rows = db.execute("SELECT id,version,decision,scope,superseded,sealed FROM runs "
                          "ORDER BY CASE WHEN id=(SELECT value FROM meta WHERE key='latest') THEN 0 ELSE 1 END,rowid DESC LIMIT 100").fetchall()
    return [dict(dict(r), superseded=bool(r['superseded']), sealed=bool(r['sealed'])) for r in rows]


def review(run_id, version, decision):
    if decision not in ('通过', '退回'): raise DomainError('DECISION', '复核状态无效')
    with connection() as db:
        cur = db.execute('UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?', (decision, run_id, version))
        if cur.rowcount != 1:
            if not db.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone(): raise DomainError('NOT_FOUND', '批次不存在', 404)
            raise DomainError('STALE', '复核版本已更新，请刷新', 409)
    return get(run_id)


def seal(run_id):
    """封存是单事务：对账不平拒绝；任一步失败整体回滚，旧封存版本与原始依据保留。"""
    with connection() as db:
        r = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if not r: raise DomainError('NOT_FOUND', '批次不存在', 404)
        body = json.loads(r['body'])
        if not body.get('reconcile', {}).get('balanced'):
            raise DomainError('UNBALANCED', '对账未平，不能封存', 409)
        from datetime import datetime, timezone
        sealed_at = datetime.now(timezone.utc).isoformat()
        cur = db.execute('UPDATE runs SET sealed=1,sealed_at=? WHERE id=? AND sealed=0', (sealed_at, run_id))
        if cur.rowcount != 1:
            raise DomainError('SEALED', '批次已封存，禁止重复封存', 409)
    return get(run_id)
