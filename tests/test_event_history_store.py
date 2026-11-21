# -*- coding: utf-8 -*-
"""Offline unit tests for tools/event_history_store.py."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)

from event_history_store import EventHistoryStore  # noqa: E402


class EventHistoryStoreTests(unittest.TestCase):
    def test_upsert_idempotency_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "events.db")
            store = EventHistoryStore(db_path)
            events = [
                {
                    "raw_event_id": "evt-002",
                    "source": "forum_a",
                    "title": "Second event",
                    "raw_text": "Details two",
                    "observed_at": "2026-11-21T02:00:00Z",
                },
                {
                    "raw_event_id": "evt-001",
                    "source": "forum_b",
                    "title": "First event",
                    "raw_text": "Details one",
                    "observed_at": "2026-11-21T01:00:00Z",
                },
            ]
            inserted = store.upsert_events("topic-alpha", events)
            self.assertEqual(inserted, 2)
            # Re-upserting same IDs updates cleanly without duplicating rows
            store.upsert_events("topic-alpha", events)
            loaded = store.load_events("topic-alpha")
            self.assertEqual([e["raw_event_id"] for e in loaded], ["evt-001", "evt-002"])

            with store.connection() as con:
                row = con.execute(
                    "SELECT content_hash, payload_hash FROM raw_events WHERE raw_event_id='evt-001'"
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(len(row[0]), 64)
            self.assertEqual(len(row[1]), 64)

    def test_commit_run_and_json_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db1 = os.path.join(tmp, "primary.db")
            json_path = os.path.join(tmp, "export.json")
            store = EventHistoryStore(db1, json_path=json_path)

            store.commit_run(
                run_id="run-101",
                topic_key="topic-beta",
                events=[
                    {
                        "raw_event_id": "evt-100",
                        "source": "news_api",
                        "source_url": "https://example.com/100",
                        "title": "Release update",
                        "raw_text": "Official patch notes released.",
                        "observed_at": "2026-11-21T03:00:00Z",
                    }
                ],
                health=[
                    {
                        "source": "news_api",
                        "status": "ok",
                        "attempts": 1,
                        "items_seen": 5,
                        "items_new": 1,
                    },
                    {
                        "source": "social_feed",
                        "status": "timeout",
                        "attempts": 1,
                        "consecutive_failures": 1,
                        "last_error_code": "ETIMEDOUT",
                    },
                ],
                outputs=[{"output_name": "digest.md", "status": "delivered", "attempts": 1}],
            )

            with store.connection() as con:
                run_row = con.execute(
                    "SELECT status FROM runs WHERE run_id='run-101'"
                ).fetchone()
                health_row = con.execute(
                    "SELECT status, last_error_code FROM source_health WHERE topic_key='topic-beta' AND source='social_feed'"
                ).fetchone()
                deliv_row = con.execute(
                    "SELECT status FROM delivery_status WHERE run_id='run-101' AND output_name='digest.md'"
                ).fetchone()
            self.assertEqual(run_row[0], "committed")
            self.assertEqual(health_row, ("timeout", "ETIMEDOUT"))
            self.assertEqual(deliv_row[0], "delivered")

            out_file = store.export_json("topic-beta")
            self.assertEqual(out_file, json_path)
            with open(json_path, encoding="utf-8") as f:
                exported = json.load(f)
            self.assertEqual(len(exported["raw_events"]), 1)

            db2 = os.path.join(tmp, "restored.db")
            restored = EventHistoryStore(db2, json_path=json_path)
            imported = restored.import_json_once("topic-beta")
            self.assertEqual(imported, 1)
            self.assertEqual(restored.load_events("topic-beta")[0]["raw_event_id"], "evt-100")


if __name__ == "__main__":
    unittest.main()
