"""Smoke tests for the deterministic end-to-end demo orchestration."""

import csv

import run_reconciliation

from creator_payout_ops.models import (
    ApprovalDecision,
    ObligationStatus,
    PaymentExecutionStatus,
    ReconciliationStatus,
    WebhookProcessingStatus,
)


def test_demo_runs_and_confirms_payment_without_duplicates(capsys, tmp_path):
    outcome = run_reconciliation.run_demo(
        database_path=tmp_path / "lifecycle.sqlite3",
        output_directory=tmp_path / "reports",
    )
    output = capsys.readouterr().out

    assert outcome["initiated_attempt"].status is PaymentExecutionStatus.PENDING
    assert outcome["obligation"].status is ObligationStatus.OUTSTANDING
    assert outcome["approved_obligation"].status is ObligationStatus.APPROVED
    assert outcome["approval"].decision is ApprovalDecision.APPROVED
    assert outcome["approval"].obligation_id == outcome["obligation"].obligation_id
    assert outcome["initiated_attempt"].obligation_id == outcome["obligation"].obligation_id
    assert outcome["initiated_attempt"].approval_id == outcome["approval"].approval_id
    assert outcome["pre_approval_message"] == "Payout obligation is not approved"
    assert outcome["confirmed_attempt"].status is PaymentExecutionStatus.PAID
    assert outcome["duplicate_webhook"].processing_status is WebhookProcessingStatus.DUPLICATE
    assert outcome["provider_payment_count"] == 1
    assert len(outcome["persisted_payment_records"]) == 1
    assert len(outcome["audit_trail"].webhook_events) == 1
    assert len(outcome["audit_trail"].confirmed_payments) == 1
    assert outcome["final_reconciliation"].status is ReconciliationStatus.PAID
    assert outcome["final_reconciliation"].outstanding_balance.is_zero()
    assert all(path.exists() for path in outcome["report_paths"].values())
    with outcome["report_paths"]["reconciliation"].open(
        newline="", encoding="utf-8"
    ) as handle:
        final_rows = {row["creator_id"]: row for row in csv.DictReader(handle)}
    assert final_rows["CR-D"]["amount_paid"] == "92.73"
    assert final_rows["CR-D"]["outstanding_balance"] == "0.00"
    assert final_rows["CR-D"]["status"] == "PAID"
    assert "Payment Before Approval: BLOCKED" in output
    assert "Duplicate Webhook After Restart" in output
    assert "Source: persisted confirmed payment history" in output
    assert "End-to-End Workflow Complete" in output
