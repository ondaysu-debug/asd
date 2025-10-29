from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
import time
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
            # seen_pools migration: ensure (chain,pool) schema
            try:
                cur = conn.execute("PRAGMA table_info(seen_pools)")
                cols = [row[1] for row in cur.fetchall()]
            except Exception:
                cols = []
            if cols and ("chain" not in cols or "pool" not in cols or "seen_ts" not in cols):
                # rename legacy table
                conn.execute("ALTER TABLE seen_pools RENAME TO seen_pools_legacy")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_pools(
                  chain TEXT NOT NULL,
                  pool  TEXT NOT NULL,
                  seen_ts INTEGER NOT NULL,
                  PRIMARY KEY(chain, pool)
                )
                """
            )
            # progress cursors
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS progress_cursors(
                  chain   TEXT NOT NULL,
                  source  TEXT NOT NULL,
                  page    INTEGER NOT NULL DEFAULT 1,
                  extra   TEXT,
                  updated_ts INTEGER NOT NULL,
                  PRIMARY KEY(chain, source)
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
    def mark_as_seen(self, conn: sqlite3.Connection, chain: str, pool: str) -> None:
        conn.execute(
            """
            INSERT INTO seen_pools(chain,pool,seen_ts) VALUES(?,?, strftime('%s','now'))
            ON CONFLICT(chain,pool) DO UPDATE SET seen_ts=strftime('%s','now')
            """,
            (chain, pool),
        )
        conn.commit()

    def get_recently_seen(self, conn: sqlite3.Connection, chain: str, ttl_min: int) -> set[str]:
        cur = conn.execute(
            """
            SELECT pool FROM seen_pools 
            WHERE chain=? AND seen_ts > strftime('%s','now') - (? * 60)
            """,
            (chain, int(ttl_min)),
        )
        return {row[0] for row in cur.fetchall()}

    def purge_seen_older_than(self, conn: sqlite3.Connection, ttl_sec: int) -> None:
        conn.execute(
            """
            DELETE FROM seen_pools WHERE seen_ts <= strftime('%s','now') - ?
            """,
            (int(ttl_sec),),
        )
        conn.commit()

    # ---------------- Progress cursors ----------------
    def get_progress(self, conn: sqlite3.Connection, chain: str, source: str) -> int:
        cur = conn.execute(
            "SELECT page FROM progress_cursors WHERE chain=? AND source=?",
            (chain, source),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 1

    def bump_progress(self, conn: sqlite3.Connection, chain: str, source: str, next_page: int) -> None:
        conn.execute(
            """
            INSERT INTO progress_cursors(chain,source,page,extra,updated_ts)
            VALUES(?,?,?,?,?)
            ON CONFLICT(chain,source) DO UPDATE SET page=excluded.page, extra=excluded.extra, updated_ts=excluded.updated_ts
            """,
            (chain, source, int(next_page), None, int(time.time())),
        )
        conn.commit()
