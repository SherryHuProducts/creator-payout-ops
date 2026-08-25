"""Smoke tests for the deterministic end-to-end demo orchestration."""

import run_reconciliation

from creator_payout_ops.models import (
    PaymentExecutionStatus,
    ReconciliationStatus,
    WebhookProcessingStatus,
)


def test_demo_runs_and_confirms_payment_without_duplicates(capsys):
    outcome = run_reconciliation.run_demo()
    output = capsys.readouterr().out

    assert outcome["initiated_attempt"].status is PaymentExecutionStatus.PENDING
    assert outcome["confirmed_attempt"].status is PaymentExecutionStatus.PAID
    assert outcome["duplicate_webhook"].processing_status is WebhookProcessingStatus.DUPLICATE
    assert outcome["provider_payment_count"] == 1
    assert outcome["final_reconciliation"].status is ReconciliationStatus.PAID
    assert outcome["final_reconciliation"].outstanding_balance.is_zero()
    assert "End-to-End Workflow Complete" in output
