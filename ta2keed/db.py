"""SQLite persistence. One file, zero setup."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .config import settings

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
  phone TEXT PRIMARY KEY, name TEXT, delivered INTEGER DEFAULT 0, refused INTEGER DEFAULT 0,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, user_id TEXT, state TEXT DEFAULT 'NEW',
  draft TEXT DEFAULT '{}', order_id TEXT, created_at REAL, updated_at REAL,
  UNIQUE(channel, user_id)
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id INTEGER, role TEXT, text TEXT, meta TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY, conv_id INTEGER, customer_phone TEXT, customer_name TEXT, address TEXT,
  zone TEXT, items TEXT, subtotal INTEGER, shipping INTEGER, total INTEGER, upsell_value INTEGER DEFAULT 0,
  risk_score REAL, risk_reasons TEXT, deposit_required INTEGER DEFAULT 0, deposit_paid INTEGER DEFAULT 0,
  status TEXT, tracking TEXT, after_hours INTEGER DEFAULT 0, outcome TEXT, created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, reference TEXT, amount INTEGER, image_hash TEXT,
  status TEXT, reason TEXT, raw TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id INTEGER, order_id TEXT, type TEXT, data TEXT, ts REAL
);
"""


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(settings.db_path, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


def q(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict | None:
    rows = q(sql, args)
    return rows[0] if rows else None


def x(sql: str, args: tuple = ()) -> int:
    with _lock:
        cur = conn().execute(sql, args)
        conn().commit()
        return cur.lastrowid


def reset(seed: bool = True) -> None:
    with _lock:
        c = conn()
        for t in ("customers", "conversations", "messages", "orders", "payments", "events"):
            c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM sqlite_sequence")
        c.commit()
    if seed:
        seed_customers()


def seed_customers() -> None:
    """Demo purchase history (the SME's past COD outcomes)."""
    path = Path(settings.store_path).with_name("customers_seed.json")
    if not path.exists():
        return
    for c in json.loads(path.read_text(encoding="utf-8")):
        x("INSERT OR REPLACE INTO customers(phone,name,delivered,refused,created_at) VALUES(?,?,?,?,?)",
          (c["phone"], c["name"], c["delivered"], c["refused"], time.time()))


# ---- conversations -------------------------------------------------------

def get_conversation(channel: str, user_id: str) -> dict:
    row = one("SELECT * FROM conversations WHERE channel=? AND user_id=?", (channel, user_id))
    if row is None:
        now = time.time()
        x("INSERT INTO conversations(channel,user_id,state,draft,created_at,updated_at) VALUES(?,?,?,?,?,?)",
          (channel, user_id, "NEW", "{}", now, now))
        row = one("SELECT * FROM conversations WHERE channel=? AND user_id=?", (channel, user_id))
    row["draft"] = json.loads(row["draft"] or "{}")
    return row


def save_conversation(conv: dict) -> None:
    x("UPDATE conversations SET state=?, draft=?, order_id=?, updated_at=? WHERE id=?",
      (conv["state"], json.dumps(conv["draft"], ensure_ascii=False), conv.get("order_id"), time.time(), conv["id"]))


def add_message(conv_id: int, role: str, text: str, meta: dict | None = None) -> None:
    x("INSERT INTO messages(conv_id,role,text,meta,ts) VALUES(?,?,?,?,?)",
      (conv_id, role, text, json.dumps(meta or {}, ensure_ascii=False), time.time()))


def history(conv_id: int, limit: int = 20) -> list[dict]:
    rows = q("SELECT role,text,meta,ts FROM messages WHERE conv_id=? ORDER BY id DESC LIMIT ?", (conv_id, limit))
    return list(reversed(rows))


def log_event(conv_id: int | None, type_: str, data: dict | None = None, order_id: str | None = None) -> None:
    x("INSERT INTO events(conv_id,order_id,type,data,ts) VALUES(?,?,?,?,?)",
      (conv_id, order_id, type_, json.dumps(data or {}, ensure_ascii=False, default=str), time.time()))


def customer(phone: str | None) -> dict | None:
    if not phone:
        return None
    return one("SELECT * FROM customers WHERE phone=?", (phone,))


def next_order_id() -> str:
    row = one("SELECT COUNT(*) AS n FROM orders")
    return f"NB-{1001 + (row['n'] if row else 0)}"
