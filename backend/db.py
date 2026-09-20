"""SQLite data layer (WAL mode, thread-safe). PostgreSQL-ready schema design."""
import json
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "blackforge.db"
_lock = threading.RLock()


def _conn():
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=60)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT DEFAULT '',
    mode TEXT DEFAULT 'STANDARD',
    speed TEXT DEFAULT 'MEDIUM',
    filters TEXT DEFAULT '{}',
    smtp INTEGER DEFAULT 0,
    allowlist TEXT DEFAULT '',
    status TEXT DEFAULT 'CREATED',
    total INTEGER DEFAULT 0,
    processed INTEGER DEFAULT 0,
    live INTEGER DEFAULT 0,
    likely INTEGER DEFAULT 0,
    invalid INTEGER DEFAULT 0,
    unknown INTEGER DEFAULT 0,
    dupes INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    created TEXT DEFAULT '',
    updated TEXT DEFAULT '',
    checkpoint TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    normalized TEXT NOT NULL,
    domain TEXT DEFAULT '',
    syntax TEXT DEFAULT '',
    dns TEXT DEFAULT '',
    has_mx INTEGER DEFAULT 0,
    mx_hosts TEXT DEFAULT '[]',
    provider TEXT DEFAULT '',
    institution TEXT DEFAULT '',
    confidence INTEGER DEFAULT 0,
    status TEXT DEFAULT 'PENDING',
    reason TEXT DEFAULT '',
    evidence TEXT DEFAULT '{}',
    updated TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_emails_job ON emails(job_id);
CREATE INDEX IF NOT EXISTS idx_emails_job_status ON emails(job_id, status);
CREATE INDEX IF NOT EXISTS idx_emails_job_id ON emails(job_id, id);
"""


def init_db():
    with _lock:
        c = _conn()
        c.executescript(SCHEMA)
        c.commit()
        c.close()


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _row_to_dict(r):
    return dict(r) if r else None


# ---------------- jobs ----------------
def create_job(name, mode, speed, filters, smtp, allowlist, total, dupes):
    with _lock:
        c = _conn()
        cur = c.execute(
            """INSERT INTO jobs (name, mode, speed, filters, smtp, allowlist, status,
                                 total, processed, created, updated, checkpoint)
               VALUES (?, ?, ?, ?, ?, ?, 'CREATED', ?, 0, ?, ?, '{}')""",
            (name, mode, speed, json.dumps(filters), 1 if smtp else 0,
             allowlist, total, _now(), _now()),
        )
        jid = cur.lastrowid
        c.execute("UPDATE jobs SET dupes=?, updated=? WHERE id=?", (dupes, _now(), jid))
        c.commit()
        c.close()
        return jid


def get_job(job_id):
    with _lock:
        c = _conn()
        r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        c.close()
        return _row_to_dict(r)


def list_jobs(limit=20):
    with _lock:
        c = _conn()
        rows = c.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        c.close()
        return [dict(r) for r in rows]


def set_job_status(job_id, status, checkpoint=None):
    with _lock:
        c = _conn()
        if checkpoint is None:
            c.execute("UPDATE jobs SET status=?, updated=? WHERE id=?",
                      (status, _now(), job_id))
        else:
            c.execute("UPDATE jobs SET status=?, checkpoint=?, updated=? WHERE id=?",
                      (status, json.dumps(checkpoint), _now(), job_id))
        c.commit()
        c.close()


def bump_job(job_id, field, by=1):
    with _lock:
        c = _conn()
        c.execute(f"UPDATE jobs SET {field}={field}+?, updated=? WHERE id=?",
                  (by, _now(), job_id))
        c.commit()
        c.close()


def save_checkpoint(job_id, position, processed):
    with _lock:
        c = _conn()
        cp = {"position": position, "processed": processed,
              "ts": _now(), "ts_epoch": int(time.time())}
        c.execute("UPDATE jobs SET checkpoint=?, updated=? WHERE id=?",
                  (json.dumps(cp), _now(), job_id))
        c.commit()
        c.close()


def reconcile_job(job_id):
    """Set processed = total - pending (counts in-flight completions). Returns processed."""
    with _lock:
        c = _conn()
        pend = c.execute("SELECT COUNT(*) AS n FROM emails WHERE job_id=? AND status='PENDING'",
                         (job_id,)).fetchone()["n"]
        tot = c.execute("SELECT total FROM jobs WHERE id=?", (job_id,)).fetchone()["total"]
        proc = tot - pend
        c.execute("UPDATE jobs SET processed=?, updated=? WHERE id=?", (proc, _now(), job_id))
        c.commit()
        c.close()
        return proc


def delete_job(job_id):
    with _lock:
        c = _conn()
        c.execute("DELETE FROM emails WHERE job_id=?", (job_id,))
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        c.commit()
        c.close()


# ---------------- emails ----------------
def insert_emails(job_id, rows):
    """rows: list of (email, normalized). Batch insert as PENDING."""
    with _lock:
        c = _conn()
        c.executemany(
            "INSERT INTO emails (job_id, email, normalized, status) VALUES (?, ?, ?, 'PENDING')",
            [(job_id, e, n) for e, n in rows],
        )
        c.commit()
        c.close()


def count_pending(job_id):
    with _lock:
        c = _conn()
        r = c.execute("SELECT COUNT(*) AS n FROM emails WHERE job_id=? AND status='PENDING'",
                      (job_id,)).fetchone()
        c.close()
        return r["n"]


def fetch_pending(job_id, after_id, limit):
    with _lock:
        c = _conn()
        rows = c.execute(
            "SELECT * FROM emails WHERE job_id=? AND status='PENDING' AND id>? ORDER BY id LIMIT ?",
            (job_id, after_id, limit)).fetchall()
        c.close()
        return [dict(r) for r in rows]


def mark_result(email_id, res):
    with _lock:
        c = _conn()
        c.execute(
            """UPDATE emails SET domain=?, syntax=?, dns=?, has_mx=?, mx_hosts=?,
               provider=?, institution=?, confidence=?, status=?, reason=?, evidence=?, updated=?
               WHERE id=?""",
            (res.get("domain", ""), res.get("syntax", ""), res.get("dns", ""),
             1 if res.get("has_mx") else 0, json.dumps(res.get("mx_hosts", [])),
             res.get("provider", ""), res.get("institution", ""),
             res.get("confidence", 0), res.get("status", "UNKNOWN"),
             res.get("reason", "")[:300], json.dumps(res.get("evidence", {}))[:4000],
             _now(), email_id),
        )
        c.commit()
        c.close()


def count_by_status(job_id):
    with _lock:
        c = _conn()
        rows = c.execute(
            "SELECT status, COUNT(*) AS n FROM emails WHERE job_id=? GROUP BY status",
            (job_id,)).fetchall()
        c.close()
        return {r["status"]: r["n"] for r in rows}


_ALLOWED_SORT = {"id": "id", "email": "email", "confidence": "confidence",
                 "domain": "domain", "status": "status", "updated": "updated"}


def get_results(job_id, status=None, provider=None, q=None, page=1, per=50,
                sort="id", direction="asc"):
    col = _ALLOWED_SORT.get(sort, "id")
    d = "DESC" if str(direction).lower() == "desc" else "ASC"
    clauses = ["job_id=?"]
    params = [job_id]
    if status and status != "ALL":
        clauses.append("status=?")
        params.append(status)
    if provider and provider != "ALL":
        clauses.append("provider=?")
        params.append(provider)
    if q:
        clauses.append("(email LIKE ? OR domain LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    where = " AND ".join(clauses)
    with _lock:
        c = _conn()
        total = c.execute(f"SELECT COUNT(*) AS n FROM emails WHERE {where}",
                          params).fetchone()["n"]
        offset = max(0, (page - 1) * per)
        rows = c.execute(
            f"SELECT * FROM emails WHERE {where} ORDER BY {col} {d} LIMIT ? OFFSET ?",
            params + [per, offset]).fetchall()
        c.close()
        return [dict(r) for r in rows], total


def iter_export(job_id, status=None, chunk=2000):
    """Yield rows in id order for streaming exports (bounded memory)."""
    last_id = 0
    while True:
        with _lock:
            c = _conn()
            if status and status != "ALL":
                rows = c.execute(
                    "SELECT * FROM emails WHERE job_id=? AND status=? AND id>? ORDER BY id LIMIT ?",
                    (job_id, status, last_id, chunk)).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM emails WHERE job_id=? AND id>? ORDER BY id LIMIT ?",
                    (job_id, last_id, chunk)).fetchall()
            c.close()
        if not rows:
            return
        for r in rows:
            last_id = r["id"]
            yield dict(r)
