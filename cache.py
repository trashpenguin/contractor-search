from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time

from config import TTL_CONTACT as _TTL_CONTACT
from config import TTL_DDG as _TTL_DDG

logger = logging.getLogger("ContractorFinder")


class SearchHistory:
    """Saves last 20 location searches to ~/.contractor_search_history.json"""

    PATH = os.path.join(os.path.expanduser("~"), ".contractor_search_history.json")
    MAX = 20

    def load(self) -> list[str]:
        try:
            with open(self.PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    return []
                return [str(x) for x in data if x]
        except Exception:
            return []

    def save(self, location: str):
        history = self.load()
        if location in history:
            history.remove(location)
        history.insert(0, location)
        try:
            with open(self.PATH, "w", encoding="utf-8") as f:
                json.dump(history[: self.MAX], f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save search history: {e}")


class ContactCache:
    """
    SQLite cache for contractor contact data.
    TTL: 7 days for contact data, 1 day for DDG results.
    """

    DB_PATH = os.path.join(os.path.expanduser("~"), ".contractor_finder_cache.db")
    TTL_CONTACT = _TTL_CONTACT
    TTL_DDG = _TTL_DDG

    def __init__(self):
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
            conn.execute(
                """CREATE TABLE IF NOT EXISTS contacts (
                key TEXT PRIMARY KEY,
                email TEXT, phone TEXT, website TEXT,
                created_at REAL
            )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS ddg_cache (
                query_hash TEXT PRIMARY KEY,
                results TEXT,
                created_at REAL
            )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_ts ON contacts(created_at)")
            conn.commit()
            self._conn = conn
        except Exception as e:
            logger.debug(f"[Cache] Init failed: {e}")

    def get_contact(self, key: str) -> dict | None:
        if not self._conn:
            return None
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT email, phone, website, created_at FROM contacts WHERE key=?", (key,)
                ).fetchone()
                if row and (time.time() - row[3]) < self.TTL_CONTACT:
                    return {"email": row[0], "phone": row[1], "website": row[2]}
        except Exception as e:
            logger.warning(f"[Cache] get_contact failed: {e}")
        return None

    def set_contact(self, key: str, email: str, phone: str, website: str):
        if not self._conn:
            return
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO contacts VALUES (?,?,?,?,?)",
                    (key, email, phone, website, time.time()),
                )
                self._conn.commit()
        except Exception as e:
            logger.warning(f"[Cache] set_contact failed: {e}")

    def get_ddg(self, query: str) -> list | None:
        if not self._conn:
            return None
        qhash = hashlib.md5(query.encode()).hexdigest()
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT results, created_at FROM ddg_cache WHERE query_hash=?", (qhash,)
                ).fetchone()
                if row and (time.time() - row[1]) < self.TTL_DDG:
                    return json.loads(row[0])
        except Exception as e:
            logger.warning(f"[Cache] get_ddg failed: {e}")
        return None

    def set_ddg(self, query: str, results: list):
        if not self._conn:
            return
        qhash = hashlib.md5(query.encode()).hexdigest()
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO ddg_cache VALUES (?,?,?)",
                    (qhash, json.dumps(results), time.time()),
                )
                self._conn.commit()
        except Exception as e:
            logger.warning(f"[Cache] set_ddg failed: {e}")

    def purge_old(self):
        if not self._conn:
            return
        cutoff = time.time() - max(self.TTL_CONTACT, self.TTL_DDG)
        try:
            with self._lock:
                self._conn.execute("DELETE FROM contacts WHERE created_at < ?", (cutoff,))
                self._conn.execute("DELETE FROM ddg_cache WHERE created_at < ?", (cutoff,))
                self._conn.commit()
        except Exception as e:
            logger.warning(f"[Cache] purge_old failed: {e}")


SEARCH_HISTORY = SearchHistory()
CACHE = ContactCache()
