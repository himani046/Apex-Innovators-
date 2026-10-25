def arbitrate(finding,verification):
 return {'agent':'Tyr','ruling_id':'ruling-a1-notice-timing','decision':'partially_supported_not_a_proven_breach' if verification.get('supports') else 'insufficient_evidence','rationale':'Accept the outage occurrence as supported by E-04. Do not conclude StratoNode breached A1 Section I.1 because provider awareness time and actual notice-delivery time are not established.','approved_facts':verification.get('supports',[]),'rejected_or_unproven_claims':['That StratoNode definitively breached A1 Section I.1.'],'action_draft':{'type':'evidence_request','subject':'Request for March 3, 2027 incident timeline and notification records','body':'Please provide the timestamp when StratoNode became aware of the March 3, 2027 CloudCore disruption, the timestamp and delivery evidence for any notification sent to Quillhub Operations, and the incident timeline supporting those records. Quillhub is reviewing the incident against Section I.1 of the Cloud Service Agreement.','citations':finding.get('citations',[]),'human_approval_required':True,'status':'draft_only_not_sent'},'confidence':0.84}


def arbitrate_contract_review(contract_id, findings, verification):
    """Produce qualified per-contract rulings and draft-only actions."""
    verified_by_id = {item.get("finding_id"): item for item in verification.get("findings", [])}
    rulings = []
    for finding in findings:
        checked = verified_by_id.get(finding.get("id"), {})
        category = str(finding.get("category", "review"))
        if category == "renewal":
            action_type = "renewal_review"
            subject = f"Review renewal and notice requirements for {contract_id}"
        elif category == "termination":
            action_type = "termination_review"
            subject = f"Review termination and cure-period language for {contract_id}"
        elif category == "penalty_or_interest":
            action_type = "financial_escalation_memo"
            subject = f"Validate penalty or interest trigger for {contract_id}"
        elif category == "notice_obligation":
            action_type = "evidence_request"
            subject = f"Confirm notice timing and delivery evidence for {contract_id}"
        elif category == "liability_or_indemnity":
            action_type = "legal_review_memo"
            subject = f"Review liability allocation in {contract_id}"
        else:
            action_type = "clause_review"
            subject = f"Review {category.replace('_', ' ')} provision in {contract_id}"
        rulings.append({
            "agent": "Tyr", "contract_id": contract_id, "finding_id": finding.get("id"),
            "decision": "requires_human_review",
            "rationale": "The source candidate is not by itself proof of breach or liability. Confirm the clause context, applicable trigger, event evidence, amendments, and counterparty performance.",
            "verification_status": checked.get("status", "not_verified"),
            "approved_facts": checked.get("supports", []),
            "unproven_claims": ["No legal breach or payable penalty is established by keyword triage alone."],
            "action_draft": {"type": action_type, "subject": subject,
                             "body": "Please review the cited source language, confirm the applicable trigger and relevant facts, and determine whether a notice or other action is appropriate. This draft is not sent automatically.",
                             "citations": finding.get("citations", []), "confidence": finding.get("confidence", 0.65),
                             "human_approval_required": True, "status": "draft_only_not_sent"}
        })
    return {"agent": "Tyr", "contract_id": contract_id, "rulings": rulings,
            "status": "complete_with_human_review" if rulings else "no_ruling_candidates"}
