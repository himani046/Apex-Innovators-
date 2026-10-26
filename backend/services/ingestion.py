import csv
import json
from pathlib import Path


def load_events(path):
    """Load JSONL event drops, preserving malformed records as parse errors."""
    events, errors = [], []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("JSONL record must be an object")
            item.setdefault("source_file", Path(path).name)
            events.append(item)
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append({"line": n, "error": str(exc), "status": "parse_error", "source_file": Path(path).name})
    return events, errors


def _first_value(row, *names):
    """Return the first non-empty field among common event-feed column names."""
    normalized = {str(key or "").strip().casefold().replace(" ", "_"): value for key, value in row.items()}
    for name in names:
        value = normalized.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def load_event_csv(path):
    """Load CSV event feeds and normalize common columns without discarding raw fields."""
    events, errors = [], []
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for line_number, row in enumerate(csv.DictReader(stream), start=2):
            if not any(str(value or "").strip() for value in row.values()):
                continue
            if None in row:
                errors.append({
                    "line": line_number,
                    "error": "CSV row has more values than the header",
                    "status": "parse_error",
                    "source_file": Path(path).name,
                })
            event = dict(row)
            event_id = _first_value(row, "event_id", "eventid", "id", "record_id", "incident_id")
            timestamp = _first_value(row, "timestamp", "event_timestamp", "event_date", "date", "created_at", "occurred_at")
            body = _first_value(row, "body", "text", "description", "event_description", "message", "details", "summary")
            contract_id = _first_value(row, "contract_id", "contractid", "document_id", "contract_ref", "agreement_id")
            if event_id:
                event["event_id"] = event_id
            elif not event.get("event_id"):
                event["event_id"] = f"{Path(path).stem}:row:{line_number}"
            if timestamp:
                event["timestamp"] = timestamp
            if body:
                event["body"] = body
            if contract_id:
                event["contract_id"] = contract_id
            event["source_file"] = Path(path).name
            event["ingestion_format"] = "csv"
            events.append(event)
    return events, errors


def load_pack(root):
    root = Path(root)
    bundle = root / "bundle"
    contracts = {
        path.stem: path.read_text(encoding="utf-8")
        for path in (bundle / "contracts").glob("*.txt")
    }
    drops, errors = {}, {}
    event_dir = bundle / "events"
    for path in sorted(event_dir.glob("*.jsonl")):
        drops[path.name], errors[path.name] = load_events(path)
    for path in sorted(event_dir.glob("*.csv")):
        drops[path.name], errors[path.name] = load_event_csv(path)

    def rows(path):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    return {
        "company_context": (bundle / "company/context.txt").read_text(encoding="utf-8"),
        "contracts": contracts,
        "manifest": json.loads((bundle / "manifest.json").read_text()),
        "clock": json.loads((root / "clock.json").read_text()),
        "ledger": rows(bundle / "data/payments_ledger.csv"),
        "holidays": rows(bundle / "data/holidays.csv"),
        "event_drops": drops,
        "parse_errors": errors,
    }
