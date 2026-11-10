"""Small transactional SQLite store with persistent job snapshots."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
import uuid


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def identifier() -> str:
    return uuid.uuid4().hex


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL, id TEXT NOT NULL, project_id TEXT, data TEXT NOT NULL, PRIMARY KEY(kind,id))')
            db.execute('CREATE INDEX IF NOT EXISTS project_records ON records(kind,project_id)')
            db.execute('CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            db.execute("INSERT OR IGNORE INTO counters(name,value) VALUES ('job',0)")
            # Upgrade databases created before sequence numbers, preserving insertion order.
            rows=db.execute("SELECT rowid,data FROM records WHERE kind='job' ORDER BY rowid").fetchall()
            sequence=max([db.execute("SELECT value FROM counters WHERE name='job'").fetchone()[0]]+
                         [int(json.loads(data).get('sequence',0)) for _,data in rows])
            for rowid,data in rows:
                job=json.loads(data)
                if 'sequence' not in job:
                    sequence+=1; job['sequence']=sequence
                    db.execute('UPDATE records SET data=? WHERE rowid=?',(json.dumps(job),rowid))
            db.execute("UPDATE counters SET value=? WHERE name='job'",(sequence,))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=20)
        try:
            db.execute('PRAGMA busy_timeout=20000')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, kind: str, id: str) -> dict | None:
        with self.lock, self.connection() as db:
            row = db.execute('SELECT data FROM records WHERE kind=? AND id=?',(kind,id)).fetchone()
            return json.loads(row[0]) if row else None

    def list(self, kind: str, project_id: str | None = None) -> list[dict]:
        with self.lock, self.connection() as db:
            if project_id is None:
                rows = db.execute('SELECT data FROM records WHERE kind=? ORDER BY rowid',(kind,)).fetchall()
            else:
                rows = db.execute('SELECT data FROM records WHERE kind=? AND project_id=? ORDER BY rowid',(kind,project_id)).fetchall()
            values = [json.loads(r[0]) for r in rows]
            return sorted(values,key=lambda value:value['sequence']) if kind=='job' else sorted(values,key=lambda value:(value.get('position',0),value.get('created_at','')))

    def put(self, kind: str, value: dict) -> dict:
        value=dict(value)
        with self.lock, self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if kind=='job':
                existing=db.execute("SELECT data FROM records WHERE kind='job' AND id=?",(value['id'],)).fetchone()
                if existing:
                    value['sequence']=json.loads(existing[0])['sequence']
                else:
                    db.execute("UPDATE counters SET value=value+1 WHERE name='job'")
                    value['sequence']=db.execute("SELECT value FROM counters WHERE name='job'").fetchone()[0]
            db.execute('INSERT INTO records(kind,id,project_id,data) VALUES (?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET project_id=excluded.project_id,data=excluded.data', (kind,value['id'],value.get('project_id'),json.dumps(value,ensure_ascii=False,allow_nan=False)))
        return value

    def delete(self, kind: str, id: str):
        with self.lock, self.connection() as db:
            db.execute('DELETE FROM records WHERE kind=? AND id=?',(kind,id))

    def delete_project(self, id: str):
        with self.lock, self.connection() as db:
            db.execute("DELETE FROM records WHERE project_id=? OR (kind='project' AND id=?)",(id,id))

    def patch(self, kind: str, id: str, **fields) -> dict | None:
        with self.lock:
            value = self.get(kind,id)
            if value is None: return None
            value.update(fields)
            value['updated_at'] = now()
            return self.put(kind,value)

    def claim_job(self) -> dict | None:
        with self.lock, self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT data FROM records WHERE kind='job' AND json_extract(data,'$.status')='queued' ORDER BY CAST(json_extract(data,'$.sequence') AS INTEGER) LIMIT 1").fetchone()
            if not row: return None
            job = json.loads(row[0])
            job.update(status='running',progress=1,updated_at=now())
            db.execute("UPDATE records SET data=? WHERE kind='job' AND id=?",(json.dumps(job),job['id']))
            return job

    def finalize_job(self, job_id: str, asset: dict) -> dict | None:
        """Commit the output asset, successful job and project timestamp together.

        A cancelled or missing job is never resurrected. The video bytes are already
        complete before this transaction; a crash may leave an unreferenced file but
        cannot expose a successful job whose asset metadata was not committed.
        """
        with self.lock, self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT data FROM records WHERE kind='job' AND id=?",(job_id,)).fetchone()
            if row is None: return None
            job=json.loads(row[0])
            if job['status']!='running': return None
            if asset.get('project_id')!=job['project_id'] or asset.get('job_id')!=job_id:
                raise ValueError('Rendered asset does not belong to this job.')
            row=db.execute("SELECT data FROM records WHERE kind='project' AND id=?",(job['project_id'],)).fetchone()
            if row is None: raise ValueError('Render project no longer exists.')
            project=json.loads(row[0]); timestamp=now()
            job.update(status='succeeded',progress=100,asset_id=asset['id'],error=None,updated_at=timestamp)
            project['updated_at']=timestamp
            db.execute("INSERT INTO records(kind,id,project_id,data) VALUES ('asset',?,?,?)",
                       (asset['id'],asset['project_id'],json.dumps(asset,ensure_ascii=False,allow_nan=False)))
            db.execute("UPDATE records SET data=? WHERE kind='job' AND id=?",(json.dumps(job,ensure_ascii=False,allow_nan=False),job_id))
            db.execute("UPDATE records SET data=? WHERE kind='project' AND id=?",(json.dumps(project,ensure_ascii=False,allow_nan=False),project['id']))
            return job

    def recover(self):
        for job in self.list('job'):
            if job['status']=='running':
                self.patch('job',job['id'],status='failed',error='The server stopped during this render. Retry to start a new render.',progress=0)
