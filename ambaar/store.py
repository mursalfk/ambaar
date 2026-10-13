# ambaar/store.py
"""
Queue persistence.

Until now the queue lived only in memory, so closing the app threw away
everything: what was staged, what was half-downloaded, what had failed and why.
For a tool whose selling point is surviving a 42 GB download, losing the queue
on a restart was the obvious gap.

SQLite rather than JSON because the queue is written on every progress update.
A JSON file rewritten that often will eventually be truncated by a crash or a
power cut, and a truncated file loses the whole queue rather than one row.
SQLite's write is atomic per transaction, so the worst case is losing the last
update rather than the list.

Writes come from the GUI thread only -- every state change arrives there as a
Qt signal -- so there is no cross-thread access to coordinate.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import fields
from pathlib import Path

from .links import normalize_url
from .engine import (BUSY, CANCELLED, KIND_UNKNOWN, PAUSED, READY, RESOLVING,
                     STAGED, Job)
from .paths import data_dir

DB_FILE = data_dir() / "queue.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    title       TEXT,
    status      TEXT,
    kind        TEXT,
    item_count  INTEGER,
    duration    INTEGER,
    uploader    TEXT,
    percent     REAL,
    size        TEXT,
    filepath    TEXT,
    folder      TEXT,
    error       TEXT,
    thumb       TEXT,
    fmt         TEXT,
    entries     TEXT,
    items       TEXT,
    sizes       TEXT,
    dest        TEXT,
    position    INTEGER,
    added_at    REAL
);
CREATE INDEX IF NOT EXISTS jobs_position ON jobs(position);

CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT,
    url         TEXT NOT NULL,
    title       TEXT,
    kind        TEXT,
    filepath    TEXT,
    folder      TEXT,
    size        TEXT,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS history_key ON history(key);
CREATE INDEX IF NOT EXISTS history_time ON history(finished_at);
"""

# Columns that mirror a Job attribute one for one.
_MIRRORED = ("job_id", "url", "title", "status", "kind", "item_count",
             "duration", "uploader", "percent", "size", "filepath",
             "folder", "error", "thumb", "fmt", "entries", "items", "sizes", "dest")


class QueueStore:
    """
    The queue, on disk.

    Every method swallows sqlite errors on purpose. A corrupt or unwritable
    database must degrade to "this session has no history", never stop the user
    downloading -- persistence is a convenience here, not the product.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else DB_FILE
        self._db: sqlite3.Connection | None = None
        self.error = ""
        self._open()

    def _open(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(self.path))
            self._db.executescript(SCHEMA)
            self._migrate()
            self._db.commit()
        except (sqlite3.Error, OSError) as e:
            self._db = None
            self.error = str(e)

    def _migrate(self) -> None:
        """Add columns introduced after a user's database was first created."""
        have = {r[1] for r in self._db.execute("PRAGMA table_info(jobs)")}
        for column in ("fmt", "entries", "items", "sizes", "dest"):
            if column not in have:
                self._db.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")

    @property
    def available(self) -> bool:
        return self._db is not None

    def close(self) -> None:
        if self._db is not None:
            try:
                self._db.commit()
                self._db.close()
            except sqlite3.Error:
                pass
            self._db = None

    # -- writing -------------------------------------------------------------- #

    def save(self, job: Job, position: int) -> None:
        if self._db is None:
            return
        values = {name: getattr(job, name, None) for name in _MIRRORED
                  if name not in ("thumb", "fmt", "entries", "items", "sizes", "dest")}
        values["thumb"] = getattr(job, "thumb", "") or ""
        for name in ("fmt", "entries", "items", "sizes", "dest"):
            values[name] = getattr(job, name, "") or ""
        values["position"] = position
        values["added_at"] = time.time()
        cols = ", ".join(values)
        marks = ", ".join(f":{k}" for k in values)
        try:
            self._db.execute(
                f"INSERT INTO jobs ({cols}) VALUES ({marks}) "
                f"ON CONFLICT(job_id) DO UPDATE SET "
                + ", ".join(f"{k}=excluded.{k}" for k in values if k != "job_id"),
                values)
            self._db.commit()
        except sqlite3.Error as e:
            self.error = str(e)

    def save_all(self, jobs: list[Job]) -> None:
        for i, job in enumerate(jobs):
            self.save(job, i)

    def remove(self, job_id: str) -> None:
        if self._db is None:
            return
        try:
            self._db.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            self._db.commit()
        except sqlite3.Error as e:
            self.error = str(e)

    def clear(self) -> None:
        if self._db is None:
            return
        try:
            self._db.execute("DELETE FROM jobs")
            self._db.commit()
        except sqlite3.Error as e:
            self.error = str(e)

    # -- history -------------------------------------------------------------- #
    #
    # The queue forgets a row when the user removes it. History is the record of
    # what finished, kept after removal, so "did I already get this?" has an
    # answer and a finished download can be found again.

    def add_history(self, job: Job) -> None:
        if self._db is None:
            return
        key = normalize_url(job.url)
        try:
            # One entry per media: downloading it again replaces the old record.
            self._db.execute("DELETE FROM history WHERE key = ?", (key,))
            self._db.execute(
                "INSERT INTO history (key, url, title, kind, filepath, folder, size,"
                " finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (key, job.url, job.title, job.kind, job.filepath, job.folder,
                 job.size, time.time()))
            self._db.commit()
        except sqlite3.Error as e:
            self.error = str(e)

    def history(self, query: str = "", limit: int = 500) -> list[dict]:
        if self._db is None:
            return []
        like = f"%{query.strip()}%"
        try:
            cur = self._db.execute(
                "SELECT id, key, url, title, kind, filepath, folder, size, finished_at "
                "FROM history WHERE (title LIKE ? OR url LIKE ?) "
                "ORDER BY finished_at DESC LIMIT ?", (like, like, limit))
            names = [d[0] for d in cur.description]
            return [dict(zip(names, row)) for row in cur.fetchall()]
        except sqlite3.Error as e:
            self.error = str(e)
            return []

    def history_find(self, url: str) -> dict | None:
        if self._db is None:
            return None
        try:
            cur = self._db.execute(
                "SELECT title, finished_at FROM history WHERE key = ?",
                (normalize_url(url),))
            row = cur.fetchone()
        except sqlite3.Error as e:
            self.error = str(e)
            return None
        return {"title": row[0], "finished_at": row[1]} if row else None

    def history_remove(self, entry_id: int) -> None:
        if self._db is None:
            return
        try:
            self._db.execute("DELETE FROM history WHERE id = ?", (entry_id,))
            self._db.commit()
        except sqlite3.Error as e:
            self.error = str(e)

    def history_clear(self) -> None:
        if self._db is None:
            return
        try:
            self._db.execute("DELETE FROM history")
            self._db.commit()
        except sqlite3.Error as e:
            self.error = str(e)

    # -- reading -------------------------------------------------------------- #

    def load(self) -> list[Job]:
        """
        Restore the queue, rewriting states that cannot survive a restart.

        A job recorded as Downloading has no worker behind it any more. It
        becomes Paused when bytes were already on disk -- Resume then continues
        from the .part file -- and Ready when they were not. Anything that never
        got as far as being classified goes back to Staged so it resolves again
        on launch.
        """
        if self._db is None:
            return []
        try:
            rows = self._db.execute(
                "SELECT * FROM jobs ORDER BY position ASC").fetchall()
            names = [d[0] for d in self._db.execute(
                "SELECT * FROM jobs LIMIT 0").description]
        except sqlite3.Error as e:
            self.error = str(e)
            return []

        known = {f.name for f in fields(Job)}
        out: list[Job] = []
        for row in rows:
            data = dict(zip(names, row))
            job = Job(url=data.get("url") or "")
            for key, value in data.items():
                if key in known and value is not None:
                    setattr(job, key, value)
            job.thumb = data.get("thumb") or ""
            for name in ("fmt", "entries", "items", "sizes", "dest"):
                setattr(job, name, data.get(name) or "")
            job.status = self._restored_status(job)
            # Live metrics are meaningless once the worker is gone.
            job.speed = job.eta = ""
            out.append(job)
        return out

    @staticmethod
    def _restored_status(job: Job) -> str:
        if job.status not in BUSY and job.status != RESOLVING:
            return job.status
        if job.kind == KIND_UNKNOWN or not job.title:
            return STAGED
        if job.percent and job.percent > 0:
            return PAUSED
        return READY


def discard_incomplete(jobs: list[Job]) -> list[Job]:
    """
    Drop rows not worth restoring.

    A cancelled job with nothing downloaded is noise on the next launch: the
    user already said no to it once.
    """
    return [j for j in jobs
            if not (j.status == CANCELLED and not (j.percent or 0) > 0)]
