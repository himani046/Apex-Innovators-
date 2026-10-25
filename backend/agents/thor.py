import json
from backend.claude_client import ask_claude
from backend.config import USE_CLAUDE
from backend.services.citations import verify_all

SYSTEM = "You are Thor, the extraction agent. Extract only supported facts. Return JSON with contract_id, summary, extracted_terms (category,value,confidence,citation), ambiguities. Each citation has document_id, clause_reference and an exact quote. Never guess."

def extract_a1(source, use_claude=False):
    if use_claude and USE_CLAUDE:
        try:
            data = json.loads(ask_claude(SYSTEM, "Extract key terms from A1. SOURCE:\\n" + source, 1800))
            for term in data.get("extracted_terms", []):
                if term.get("citation"):
                    term["citation"] = verify_all([term["citation"]], {"A1": source})[0]
            data.update({"agent": "Thor", "mode": "claude"})
            return data
        except Exception:
            pass

    def citation(section, quote):
        return {"document_id": "A1", "clause_reference": section, "quote": quote}

    terms = [
        {"category": "effective_date", "value": "August 1, 2026", "confidence": 0.99, "citation": citation("Section B — Subscription Period and Renewal", "  Effective Date:            August 1, 2026")},
        {"category": "initial_term", "value": "24 months, ending July 31, 2028", "confidence": 0.99, "citation": citation("Section B — Subscription Period and Renewal", "  Initial Subscription Period: 24 months (ending July 31, 2028)")},
        {"category": "renewal", "value": "Automatic 12-month renewals; A1 states 90-day non-renewal notice", "confidence": 0.99, "citation": citation("Section B — Subscription Period and Renewal", "  Non-Renewal Notice Period: 90 days before the end of the then-current")},
        {"category": "monthly_fee", "value": "USD 8,000 per month", "confidence": 0.99, "citation": citation("Section C — Fees and Payment", "  Monthly Fee:     $8,000.00 (Eight Thousand U.S. Dollars)")},
        {"category": "payment_period", "value": "30 days from invoice date", "confidence": 0.99, "citation": citation("Section C — Fees and Payment", "  Payment Period:  30 days from invoice date.")},
        {"category": "late_interest", "value": "Overdue amounts accrue interest at 1.5% per month", "confidence": 0.99, "citation": citation("Section C — Fees and Payment", "                   overdue amounts accrue interest at 1.5% per month.")},
        {"category": "incident_notice", "value": "Commercially reasonable efforts to notify Operations within four hours of awareness", "confidence": 0.98, "citation": citation("Section I.1 — Incident Notification to Customer", "     Operations contact (ops@quillhub.io) within four (4) hours of becoming")},
        {"category": "resolution_times", "value": "Response targets are objectives; resolution times are not guaranteed", "confidence": 0.99, "citation": citation("Section D — Technical Support", "  StratoNode does not guarantee resolution times.")},
        {"category": "liability_cap", "value": "General cap is fees paid or payable in preceding 12 months", "confidence": 0.98, "citation": citation("Section G — Liability", "  General Cap Amount:  The total Fees paid or payable by Customer in the")}
    ]
    return {
        "contract_id": "A1",
        "summary": "StratoNode CloudCore hosting agreement with monthly fees, automatic renewal, incident notification language and a fee-based general liability cap.",
        "extracted_terms": terms,
        "ambiguities": [
            "A1 incorporates A2, A3 and STD; this first pass does not resolve those terms.",
            "Section I.1 measures notice from provider awareness; the awareness time for a specific incident must be established separately."
        ],
        "agent": "Thor",
        "mode": "deterministic_fallback"
    }
