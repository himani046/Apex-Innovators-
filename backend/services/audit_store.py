"""Persistent audit history for Odin runs, findings, evidence and human decisions.

SQLite is used so audit records survive process restarts. The database path can
be overridden with ODIN_AUDIT_DB; the default is data/odin_audit.sqlite3.
"""
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "odin_audit.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


class AuditStore:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path or os.environ.get("ODIN_AUDIT_DB", str(_DEFAULT_DB)))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        connection = sqlite3.connect(str(self.db_path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _connection(self):
        """Commit/rollback transactions and always close SQLite handles.

        sqlite3.Connection's own context manager does not close the connection,
        which can lock temporary database files on Windows after a test.
        """
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _init_db(self):
        with self._connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS audit_runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                as_of_date TEXT,
                status TEXT,
                input_fingerprint TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                finding_id TEXT,
                details_json TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES audit_runs(run_id)
            );
            CREATE INDEX IF NOT EXISTS idx_audit_events_run ON audit_events(run_id, event_id);
            CREATE TABLE IF NOT EXISTS audit_findings (
                finding_id TEXT PRIMARY KEY,
                contract_id TEXT,
                claim TEXT,
                status TEXT,
                severity TEXT,
                current_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_decisions (
                decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                finding_id TEXT,
                action_id TEXT NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')),
                reviewer TEXT NOT NULL,
                note TEXT NOT NULL,
                decided_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES audit_runs(run_id)
            );
            """)

    def record_run(self, payload: dict) -> dict:
        run_id = str(payload.get("run_id") or ("odin-" + hashlib.sha256(_json(payload).encode()).hexdigest()[:16]))
        created_at = _now()
        fingerprint = hashlib.sha256(_json({
            "as_of_date": payload.get("as_of_date"),
            "portfolio_extraction": payload.get("portfolio_extraction"),
            "contract_graph": payload.get("contract_graph"),
            "source_fingerprint": payload.get("source_fingerprint"),
            "company_context": payload.get("company_context"),
            "contracts": payload.get("contracts"),
        }).encode("utf-8")).hexdigest()
        snapshot = dict(payload)
        snapshot["run_id"] = run_id
        with self._connection() as db:
            existing = db.execute("SELECT run_id FROM audit_runs WHERE run_id=?", (run_id,)).fetchone()
            if existing:
                run_id = run_id + "-" + created_at.replace(":", "").replace("-", "")
                snapshot["run_id"] = run_id
            db.execute(
                "INSERT INTO audit_runs(run_id,created_at,as_of_date,status,input_fingerprint,payload_json) VALUES(?,?,?,?,?,?)",
                (run_id, created_at, snapshot.get("as_of_date"), snapshot.get("status"), fingerprint, _json(snapshot)),
            )
            db.execute(
                "INSERT INTO audit_events(run_id,occurred_at,event_type,actor,details_json) VALUES(?,?,?,?,?)",
                (run_id, created_at, "run_completed", "system", _json({
                    "status": snapshot.get("status"),
                    "as_of_date": snapshot.get("as_of_date"),
                    "input_fingerprint": fingerprint,
                })),
            )
            finding = snapshot.get("evidence_grounded_finding") or {}
            if finding:
                self._record_finding(db, run_id, finding, created_at)
            for item in snapshot.get("agent_messages", []) or []:
                db.execute(
                    "INSERT INTO audit_events(run_id,occurred_at,event_type,actor,details_json) VALUES(?,?,?,?,?)",
                    (run_id, created_at, "agent_message", str(item.get("from") or "agent"), _json(item)),
                )
            gaps = (snapshot.get("verification") or {}).get("evidence_gaps", [])
            if gaps:
                db.execute(
                    "INSERT INTO audit_events(run_id,occurred_at,event_type,actor,details_json) VALUES(?,?,?,?,?)",
                    (run_id, created_at, "evidence_gaps_recorded", "Heimdall", _json({"remaining_gaps": gaps})),
                )
        return {"run_id": run_id, "created_at": created_at, "input_fingerprint": fingerprint}

    def update_run_payload(self, run_id: str, payload: dict, actor: str = "system",
                          event_type: str = "run_state_updated", details: dict | None = None) -> dict:
        """Persist a state update to an existing run and append an audit event.

        The existing run ID and original input fingerprint remain stable. This is
        intended for targeted re-extraction and other bounded workflow updates;
        it does not approve or execute any recommended action.
        """
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dictionary")
        actor = str(actor or "system").strip()[:120] or "system"
        event_type = str(event_type or "run_state_updated").strip()[:120] or "run_state_updated"
        now = _now()
        snapshot = dict(payload)
        snapshot["run_id"] = str(run_id)
        with self._connection() as db:
            row = db.execute(
                "SELECT input_fingerprint FROM audit_runs WHERE run_id=?", (str(run_id),)
            ).fetchone()
            if not row:
                raise KeyError("run not found")
            db.execute(
                "UPDATE audit_runs SET status=?, as_of_date=?, payload_json=? WHERE run_id=?",
                (snapshot.get("status"), snapshot.get("as_of_date"), _json(snapshot), str(run_id)),
            )
            db.execute(
                "INSERT INTO audit_events(run_id,occurred_at,event_type,actor,details_json) VALUES(?,?,?,?,?)",
                (str(run_id), now, event_type, actor, _json(details or {})),
            )
        return {"run_id": str(run_id), "updated_at": now, "input_fingerprint": row["input_fingerprint"]}

    def _record_finding(self, db, run_id, finding, occurred_at):
        finding_id = str(finding.get("finding_id") or "RISK-UNKNOWN")
        current = db.execute("SELECT current_json FROM audit_findings WHERE finding_id=?", (finding_id,)).fetchone()
        current_json = _json(finding)
        if current:
            previous = json.loads(current["current_json"])
            if previous != finding:
                db.execute(
                    "INSERT INTO audit_events(run_id,occurred_at,event_type,actor,finding_id,details_json) VALUES(?,?,?,?,?,?)",
                    (run_id, occurred_at, "finding_changed", "system", finding_id,
                     _json({"previous": previous, "current": finding})),
                )
        else:
            db.execute(
                "INSERT INTO audit_events(run_id,occurred_at,event_type,actor,finding_id,details_json) VALUES(?,?,?,?,?,?)",
                (run_id, occurred_at, "finding_created", "system", finding_id, current_json),
            )
        db.execute("""
            INSERT INTO audit_findings(finding_id,contract_id,claim,status,severity,current_json,updated_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(finding_id) DO UPDATE SET contract_id=excluded.contract_id,
            claim=excluded.claim,status=excluded.status,severity=excluded.severity,
            current_json=excluded.current_json,updated_at=excluded.updated_at
        """, (finding_id, finding.get("contract_id"), finding.get("claim"), finding.get("status"),
              finding.get("severity"), current_json, occurred_at))
        for evidence in finding.get("evidence", []) or []:
            db.execute(
                "INSERT INTO audit_events(run_id,occurred_at,event_type,actor,finding_id,details_json) VALUES(?,?,?,?,?,?)",
                (run_id, occurred_at, "evidence_provenance", "system", finding_id, _json({
                    "document_id": evidence.get("document_id"),
                    "clause_reference": evidence.get("clause_reference"),
                    "quote": evidence.get("quote"),
                    "verified": bool(evidence.get("verified")),
                    "verification_note": evidence.get("verification_note"),
                })),
            )

    def list_runs(self, limit=25):
        limit = max(1, min(int(limit), 100))
        with self._connection() as db:
            rows = db.execute("SELECT run_id,created_at,as_of_date,status,input_fingerprint FROM audit_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, run_id):
        with self._connection() as db:
            row = db.execute("SELECT * FROM audit_runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["payload"] = json.loads(result.pop("payload_json"))
            result["events"] = [dict(event) for event in db.execute(
                "SELECT event_id,occurred_at,event_type,actor,finding_id,details_json FROM audit_events WHERE run_id=? ORDER BY event_id",
                (run_id,),
            ).fetchall()]
            for event in result["events"]:
                event["details"] = json.loads(event.pop("details_json"))
            result["decisions"] = [dict(decision) for decision in db.execute(
                "SELECT decision_id,run_id,finding_id,action_id,decision,reviewer,note,decided_at FROM audit_decisions WHERE run_id=? ORDER BY decision_id",
                (run_id,),
            ).fetchall()]
            return result

    def decide(self, run_id, action_id, decision, reviewer, note=""):
        decision = str(decision).strip().lower()
        reviewer = str(reviewer).strip()
        note = str(note or "").strip()
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        if not reviewer:
            raise ValueError("reviewer is required")
        with self._connection() as db:
            run = db.execute("SELECT payload_json FROM audit_runs WHERE run_id=?", (run_id,)).fetchone()
            if not run:
                raise KeyError("run not found")
            payload = json.loads(run["payload_json"])
            draft = payload.get("action_draft") or (payload.get("ruling") or {}).get("action_draft") or {}
            if not draft:
                raise ValueError("this run has no action draft to review")
            allowed_ids = {str(draft.get("action_id") or draft.get("id") or "recommended-action")}
            if str(action_id) not in allowed_ids:
                raise ValueError("action_id does not match the run's draft action")
            now = _now()
            finding_id = (payload.get("evidence_grounded_finding") or {}).get("finding_id")
            db.execute(
                "INSERT INTO audit_decisions(run_id,finding_id,action_id,decision,reviewer,note,decided_at) VALUES(?,?,?,?,?,?,?)",
                (run_id, finding_id, str(action_id), decision, reviewer, note, now),
            )
            db.execute(
                "INSERT INTO audit_events(run_id,occurred_at,event_type,actor,finding_id,details_json) VALUES(?,?,?,?,?,?)",
                (run_id, now, "human_decision", reviewer, finding_id,
                 _json({"action_id": action_id, "decision": decision, "reviewer": reviewer, "note": note,
                        "consequential_action_executed": False})),
            )
        return {"run_id": run_id, "action_id": str(action_id), "decision": decision,
                "reviewer": reviewer, "note": note, "decided_at": now,
                "consequential_action_executed": False}


audit_store = AuditStore()
