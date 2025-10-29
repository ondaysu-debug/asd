from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .config import Config


class Storage:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._jsonl_lock = threading.Lock()
        self._ensure_db()

    def _ensure_db(self) -> None:
        if not self._cfg.db_path.parent.exists():
            self._cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self._cfg.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state(
                  pool TEXT PRIMARY KEY,
                  last_alert_ts INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_pools(
                  pool TEXT PRIMARY KEY,
                  last_seen_ts INTEGER
                )
                """
            )

    def get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._cfg.db_path))

    def get_last_alert_ts(self, conn: sqlite3.Connection, pool: str) -> int | None:
        cur = conn.execute("SELECT last_alert_ts FROM state WHERE pool=?", (pool,))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def set_last_alert_ts(self, conn: sqlite3.Connection, pool: str, ts: int) -> None:
        conn.execute(
            """
            INSERT INTO state(pool,last_alert_ts) VALUES(?,?)
            ON CONFLICT(pool) DO UPDATE SET last_alert_ts=excluded.last_alert_ts
            """,
            (pool, ts),
        )
        conn.commit()

    def append_jsonl(self, obj: dict[str, Any]) -> None:
        if not self._cfg.save_candidates:
            return
        path = self._cfg.candidates_path
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(obj, ensure_ascii=False)
        with self._jsonl_lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    # ---------------- Seen cache helpers ----------------
    def mark_as_seen(self, conn: sqlite3.Connection, pool: str) -> None:
        conn.execute(
            """
            INSERT INTO seen_pools(pool,last_seen_ts) VALUES(?, strftime('%s','now'))
            ON CONFLICT(pool) DO UPDATE SET last_seen_ts=strftime('%s','now')
            """,
            (pool,),
        )
        conn.commit()

    def get_recently_seen(self, conn: sqlite3.Connection, ttl_sec: int) -> set[str]:
        cur = conn.execute(
            """
            SELECT pool FROM seen_pools WHERE last_seen_ts > strftime('%s','now') - ?
            """,
            (int(ttl_sec),),
        )
        return {row[0] for row in cur.fetchall()}

    def purge_seen_older_than(self, conn: sqlite3.Connection, ttl_sec: int) -> None:
        conn.execute(
            """
            DELETE FROM seen_pools WHERE last_seen_ts <= strftime('%s','now') - ?
            """,
            (int(ttl_sec),),
        )
        conn.commit()
