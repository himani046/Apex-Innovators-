"""Persistent, source-labeled event ingestion for contract monitoring.

Stored events are durable inputs, not independently authenticated facts. Every
record is marked unverified until an external trust/verification integration is
added.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import date, datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class EventStore:
    def __init__(self, db_path: str | Path | None = None):
        default_path = Path(__file__).resolve().parents[2] / "data" / "odin_events.sqlite3"
        self.db_path = Path(db_path or os.environ.get("ODIN_EVENT_DB", str(default_path)))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        connection = sqlite3.connect(str(self.db_path), timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _init_db(self):
        with self._connection() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS ingested_events (
                    source TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    occurred_at TEXT,
                    received_at TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(source, event_id)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_ingested_events_date ON ingested_events(occurred_at)")
            db.execute("""
                CREATE TABLE IF NOT EXISTS ingested_event_revisions (
                    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    previous_payload_hash TEXT NOT NULL,
                    new_payload_hash TEXT NOT NULL,
                    previous_payload_json TEXT NOT NULL,
                    new_payload_json TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_event_revisions_key ON ingested_event_revisions(source,event_id,revision_id)")

    def ingest(self, source: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        source = str(source or "").strip()
        if not source or len(source) > 120:
            raise ValueError("source must contain 1–120 characters")
        accepted = 0
        duplicates = 0
        updated = 0
        rejected: list[dict[str, Any]] = []
        event_results: list[dict[str, Any]] = []
        received_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as db:
            for index, raw in enumerate(events):
                if not isinstance(raw, dict):
                    rejected.append({"index": index, "reason": "record_not_object"})
                    continue
                body = str(raw.get("body", raw.get("text", raw.get("description", "")))).strip()
                if not body:
                    rejected.append({"index": index, "reason": "missing_body"})
                    continue
                timestamp = str(raw.get("timestamp", raw.get("date", ""))).strip() or None
                if timestamp:
                    try:
                        date.fromisoformat(timestamp[:10])
                    except ValueError:
                        rejected.append({"index": index, "event_id": raw.get("event_id", raw.get("id")), "reason": "invalid_timestamp"})
                        continue
                event_id = str(raw.get("event_id", raw.get("id", ""))).strip()
                if not event_id:
                    seed = source + "\n" + str(timestamp or "") + "\n" + body
                    event_id = "evt-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]
                if len(event_id) > 160:
                    rejected.append({"index": index, "event_id": event_id[:40], "reason": "event_id_too_long"})
                    continue
                payload = dict(raw)
                payload.update({
                    "event_id": event_id,
                    "body": body,
                    "timestamp": timestamp,
                    "source": source,
                    "source_verified": False,
                    "source_authenticity_verified": False,
                    "ingestion_status": "persisted_unverified_source",
                })
                payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
                previous = db.execute(
                    "SELECT payload_hash,payload_json FROM ingested_events WHERE source=? AND event_id=?",
                    (source, event_id),
                ).fetchone()
                if previous and previous["payload_hash"] == payload_hash:
                    duplicates += 1
                    event_results.append({"source": source, "event_id": event_id, "status": "duplicate_unchanged"})
                    continue
                if previous:
                    updated += 1
                    event_status = "updated"
                    db.execute(
                        """INSERT INTO ingested_event_revisions(
                            source,event_id,changed_at,previous_payload_hash,new_payload_hash,
                            previous_payload_json,new_payload_json
                        ) VALUES(?,?,?,?,?,?,?)""",
                        (source, event_id, received_at, previous["payload_hash"], payload_hash,
                         previous["payload_json"], json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)),
                    )
                else:
                    accepted += 1
                    event_status = "inserted"
                db.execute(
                    """INSERT INTO ingested_events(source,event_id,occurred_at,received_at,payload_hash,payload_json)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(source,event_id) DO UPDATE SET
                       occurred_at=excluded.occurred_at, received_at=excluded.received_at,
                       payload_hash=excluded.payload_hash, payload_json=excluded.payload_json""",
                    (source, event_id, timestamp, received_at, payload_hash,
                     json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)),
                )
                event_results.append({"source": source, "event_id": event_id, "status": event_status})
        return {
            "status": "ingestion_completed_with_review",
            "source": source,
            "counts": {"received": len(events), "inserted": accepted, "updated": updated,
                       "duplicates": duplicates, "rejected": len(rejected)},
            "events": event_results,
            "rejected": rejected,
            "source_authenticity_verified": False,
            "notice": "Events are durably stored but not independently authenticated; review provenance before relying on them.",
        }

    def list_events(self, as_of: str | None = None, limit: int = 1000) -> dict[str, Any]:
        if limit < 1 or limit > 5000:
            raise ValueError("limit must be between 1 and 5000")
        clock = date.fromisoformat(as_of) if as_of else None
        with self._connection() as db:
            rows = db.execute(
                """SELECT e.source,e.event_id,e.occurred_at,e.received_at,e.payload_json,
                          (SELECT COUNT(*) FROM ingested_event_revisions r
                           WHERE r.source=e.source AND r.event_id=e.event_id) AS revision_count,
                          (SELECT MAX(changed_at) FROM ingested_event_revisions r
                           WHERE r.source=e.source AND r.event_id=e.event_id) AS last_changed_at
                   FROM ingested_events e
                   ORDER BY COALESCE(e.occurred_at,''),e.source,e.event_id LIMIT ?""",
                (limit,),
            ).fetchall()
        events = []
        future_excluded = 0
        for row in rows:
            payload = json.loads(row["payload_json"])
            timestamp = str(payload.get("timestamp") or "")
            if clock and timestamp:
                try:
                    if date.fromisoformat(timestamp[:10]) > clock:
                        future_excluded += 1
                        continue
                except ValueError:
                    continue
            payload["source"] = row["source"]
            payload["source_verified"] = False
            payload["source_authenticity_verified"] = False
            payload["revision_count"] = row["revision_count"]
            payload["last_changed_at"] = row["last_changed_at"]
            payload["change_detected"] = row["revision_count"] > 0
            events.append(payload)
        return {
            "events": events,
            "count": len(events),
            "future_events_excluded": future_excluded,
            "source_authenticity_verified": False,
        }
