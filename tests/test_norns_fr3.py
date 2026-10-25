from backend.agents.norns import build_portfolio_timeline


def test_simulated_clock_reclassifies_deadline_and_payment_history():
    workstreams = {"workstreams": [{
        "id": "contract-A1", "primary_contract_id": "A1",
        "deadlines": [],
        "extracted_obligations": [],
        "financial_exposure": {"amounts_found": []},
    }]}
    operations = {"timeline": {"milestones": [{
        "contract_id": "A1", "date": "2027-03-10", "title": "Payment due by 2027-03-10",
        "date_type": "action_deadline", "action_required_by_date": True,
        "evidence": {"quote": "Payment due by 2027-03-10"},
    }]}, "financial_reconciliation": {"payment_ledger_candidates": [{
        "event_id": "p1", "event_source": "payments_ledger.csv", "timestamp": "2027-03-09",
        "transaction_signal": "paid", "summary": "Invoice INV-1 paid", "contract_id": "A1",
        "contract_match_status": "explicit_document_id", "amounts_found": ["$100.00"],
    }]}}
    earlier = build_portfolio_timeline(workstreams, operations, "2027-03-09")
    later = build_portfolio_timeline(workstreams, operations, "2027-03-11")
    assert earlier["items"][0]["status"] == "upcoming"
    assert later["items"][0]["status"] == "overdue"
    payment = next(item for item in later["items"] if item["date_type"] == "payment_record")
    assert payment["status"] == "recorded_paid"
    assert later["clock"]["recomputed"] is True


def test_projection_only_quantifies_explicit_conditional_fixed_penalty():
    workstreams = {"workstreams": [{
        "id": "contract-A1", "primary_contract_id": "A1", "deadlines": [],
        "financial_exposure": {"amounts_found": []},
        "extracted_obligations": [{
            "category": "late payment penalty",
            "citation": {
                "quote": "If payment is overdue, a fixed penalty of $500 applies.",
                "document_id": "A1", "clause_reference": "7.2", "verified": True,
            },
        }],
    }]}
    result = build_portfolio_timeline(workstreams, {"timeline": {"milestones": []},
        "financial_reconciliation": {"payment_ledger_candidates": []}}, "2027-03-15")
    projection = result["worst_case_projection"]
    assert projection["known_conditional_fixed_penalty_total"] == 500.0
    assert projection["known_conditional_items"] == 1
    assert "not proof" in " ".join(projection["limitations"]).lower()


def test_no_amount_is_invented_for_percentage_without_principal():
    workstreams = {"workstreams": [{
        "id": "contract-A1", "primary_contract_id": "A1", "deadlines": [],
        "financial_exposure": {"amounts_found": []},
        "extracted_obligations": [{
            "category": "interest on overdue payment",
            "citation": {
                "quote": "Interest of 2% per month applies to overdue payments.",
                "document_id": "A1", "clause_reference": "8.1", "verified": True,
            },
        }],
    }]}
    result = build_portfolio_timeline(workstreams, {"timeline": {"milestones": []},
        "financial_reconciliation": {"payment_ledger_candidates": []}}, "2027-03-15")
    projection = result["worst_case_projection"]
    assert projection["known_conditional_fixed_penalty_total"] is None
    assert projection["unknown_or_unquantified_items"] == 1
