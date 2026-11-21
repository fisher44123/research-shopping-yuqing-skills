"""SQLite-backed event history with JSON compatibility fallback."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_events (
    raw_event_id TEXT PRIMARY KEY,
    topic_key TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    title TEXT,
    raw_text TEXT,
    observed_at TEXT,
    captured_at TEXT,
    content_type TEXT,
    content_hash TEXT,
    payload_hash TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_events_topic_time
    ON raw_events(topic_key, observed_at);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    topic_key TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS delivery_status (
    run_id TEXT NOT NULL,
    output_name TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(run_id, output_name)
);
CREATE TABLE IF NOT EXISTS source_health (
    topic_key TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    items_seen INTEGER NOT NULL DEFAULT 0,
    items_new INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_error_code TEXT,
    last_error TEXT,
    paused_until TEXT,
    PRIMARY KEY(topic_key, source)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _event_hashes(event: dict, payload_str: str) -> tuple[str, str]:
    content_hash = str(event.get("content_hash") or "").strip()
    if not content_hash:
        basis = f"{event.get('title', '')}\n{event.get('raw_text', '')}"
        content_hash = hashlib.sha256(basis.encode("utf-8", errors="replace")).hexdigest()
    payload_hash = str(event.get("payload_hash") or "").strip()
    if not payload_hash:
        payload_hash = hashlib.sha256(payload_str.encode("utf-8", errors="replace")).hexdigest()
    return content_hash, payload_hash


class EventHistoryStore:
    """SQLite primary store; callers can fall back to the legacy JSON file."""

    def __init__(self, db_path: str, json_path: str | None = None):
        self.db_path = db_path
        self.json_path = json_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        con.execute("PRAGMA busy_timeout=30000")
        try:
            con.executescript(SCHEMA)
            # 兼容已经存在的旧库：新增证据 hash 字段时在线迁移，不破坏历史数据。
            for column in ("content_hash", "payload_hash"):
                try:
                    con.execute("ALTER TABLE raw_events ADD COLUMN %s TEXT" % column)
                except sqlite3.OperationalError:
                    pass
            yield con
        finally:
            con.close()

    def import_json_once(self, topic_key: str) -> int:
        if not self.json_path or not os.path.exists(self.json_path):
            return 0
        try:
            with open(self.json_path, encoding="utf-8") as f:
                data = json.load(f) or {}
            events = data.get("raw_events") or []
        except (OSError, ValueError, TypeError):
            return 0
        return self.upsert_events(topic_key, events)

    def upsert_events(self, topic_key: str, events: Iterable[dict]) -> int:
        rows = [e for e in events if isinstance(e, dict) and e.get("raw_event_id")]
        if not rows:
            return 0
        inserted = 0
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            for event in rows:
                event_id = str(event["raw_event_id"])
                payload_str = json.dumps(event, ensure_ascii=False, sort_keys=True)
                content_hash, payload_hash = _event_hashes(event, payload_str)
                cur = con.execute(
                    """INSERT INTO raw_events
                    (raw_event_id, topic_key, source, source_url, title, raw_text,
                     observed_at, captured_at, content_type, content_hash, payload_hash,
                     payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(raw_event_id) DO UPDATE SET
                      topic_key=excluded.topic_key, source=excluded.source,
                      source_url=excluded.source_url, title=excluded.title,
                      raw_text=excluded.raw_text, observed_at=excluded.observed_at,
                      captured_at=excluded.captured_at, content_type=excluded.content_type,
                      content_hash=excluded.content_hash, payload_hash=excluded.payload_hash,
                      payload_json=excluded.payload_json""",
                    (event_id, topic_key, str(event.get("source", "")),
                     str(event.get("source_url", "")), str(event.get("title", "")),
                     str(event.get("raw_text", "")), str(event.get("observed_at", "")),
                     str(event.get("captured_at", "")), str(event.get("content_type", "raw")),
                     content_hash, payload_hash, payload_str, _now()),
                )
                inserted += int(cur.rowcount > 0)
            con.commit()
        return inserted

    def load_events(self, topic_key: str) -> list[dict]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT payload_json FROM raw_events WHERE topic_key=? ORDER BY observed_at, raw_event_id",
                (topic_key,),
            ).fetchall()
        out = []
        for (payload,) in rows:
            try:
                item = json.loads(payload)
            except (ValueError, TypeError):
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def commit_run(self, run_id: str, topic_key: str, events: Iterable[dict], health: Iterable[dict], outputs: Iterable[dict] = ()) -> None:
        """原始事件、健康状态、运行状态和投递记录一次性提交。"""
        rows = [e for e in events if isinstance(e, dict) and e.get("raw_event_id")]
        health_rows = [r for r in health if isinstance(r, dict) and r.get("source")]
        output_rows = [r for r in outputs if isinstance(r, dict) and r.get("output_name")]
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            for event in rows:
                event_id = str(event["raw_event_id"])
                payload_str = json.dumps(event, ensure_ascii=False, sort_keys=True)
                content_hash, payload_hash = _event_hashes(event, payload_str)
                con.execute(
                    """INSERT INTO raw_events
                    (raw_event_id, topic_key, source, source_url, title, raw_text, observed_at, captured_at, content_type, content_hash, payload_hash, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(raw_event_id) DO UPDATE SET content_hash=excluded.content_hash, payload_hash=excluded.payload_hash, payload_json=excluded.payload_json, observed_at=excluded.observed_at""",
                    (event_id, topic_key, str(event.get("source", "")), str(event.get("source_url", "")),
                     str(event.get("title", "")), str(event.get("raw_text", "")), str(event.get("observed_at", "")),
                     str(event.get("captured_at", "")), str(event.get("content_type", "raw")),
                     content_hash, payload_hash, payload_str, _now()),
                )
            for row in health_rows:
                source = str(row["source"])
                con.execute(
                    """INSERT INTO source_health (topic_key, source, status, attempts, items_seen, items_new, consecutive_failures, last_attempt_at, last_success_at, last_error_code, last_error, paused_until)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(topic_key, source) DO UPDATE SET status=excluded.status, attempts=excluded.attempts, items_seen=excluded.items_seen, items_new=excluded.items_new, consecutive_failures=excluded.consecutive_failures, last_attempt_at=excluded.last_attempt_at, last_success_at=excluded.last_success_at, last_error_code=excluded.last_error_code, last_error=excluded.last_error, paused_until=excluded.paused_until""",
                    (topic_key, source, str(row.get("status", "unknown")), int(row.get("attempts", 0) or 0),
                     int(row.get("items_seen", 0) or 0), int(row.get("items_new", 0) or 0), int(row.get("consecutive_failures", 0) or 0),
                     str(row.get("last_attempt_at", "")), str(row.get("last_success_at", "")), str(row.get("last_error_code", "")), str(row.get("last_error", "")), str(row.get("paused_until", ""))),
                )
            now = _now()
            con.execute("INSERT OR REPLACE INTO runs(run_id, topic_key, stage, status, updated_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?)", (run_id, topic_key, "event_layer", "committed", now, "{}"))
            for output in output_rows:
                con.execute("INSERT OR REPLACE INTO delivery_status(run_id, output_name, status, attempts, last_error, updated_at) VALUES (?, ?, ?, ?, ?, ?)", (run_id, str(output["output_name"]), str(output.get("status", "pending")), int(output.get("attempts", 0) or 0), str(output.get("last_error", "")), now))
            con.commit()

    def upsert_health(self, topic_key: str, rows: Iterable[dict]) -> None:
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            for row in rows:
                source = str(row.get("source", ""))
                if not source:
                    continue
                con.execute(
                    """INSERT INTO source_health
                    (topic_key, source, status, attempts, items_seen, items_new,
                     consecutive_failures, last_attempt_at, last_success_at,
                     last_error_code, last_error, paused_until)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(topic_key, source) DO UPDATE SET
                      status=excluded.status, attempts=excluded.attempts,
                      items_seen=excluded.items_seen, items_new=excluded.items_new,
                      consecutive_failures=excluded.consecutive_failures,
                      last_attempt_at=excluded.last_attempt_at,
                      last_success_at=excluded.last_success_at,
                      last_error_code=excluded.last_error_code,
                      last_error=excluded.last_error, paused_until=excluded.paused_until""",
                    (topic_key, source, str(row.get("status", "unknown")),
                     int(row.get("attempts", 0) or 0), int(row.get("items_seen", 0) or 0),
                     int(row.get("items_new", 0) or 0), int(row.get("consecutive_failures", 0) or 0),
                     str(row.get("last_attempt_at", "")), str(row.get("last_success_at", "")),
                     str(row.get("last_error_code", "")), str(row.get("last_error", "")),
                     str(row.get("paused_until", ""))),
                )
            con.commit()

    def export_json(self, topic_key: str) -> str | None:
        if not self.json_path:
            return None
        payload = {"schema_version": "1.0", "updated_at": _now(), "raw_events": self.load_events(topic_key)}
        directory = os.path.dirname(os.path.abspath(self.json_path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="event-history-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.json_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return self.json_path
