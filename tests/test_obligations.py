"""Tests for payout obligation creation and approval transitions."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from creator_payout_ops.models import (
    ApprovalDecision,
    CreatorReconciliationResult,
    ObligationStatus,
    ReconciliationStatus,
)
from creator_payout_ops.obligations import (
    ObligationCreationError,
    ObligationTransitionError,
    create_payout_obligation,
    record_approval_decision,
)

APPROVED_AT = datetime(2026, 1, 31, 12, 0, tzinfo=timezone.utc)


def reconciliation(
    status=ReconciliationStatus.READY_TO_PAY,
    expected="245.00",
    paid="0.00",
    outstanding="245.00",
):
    return CreatorReconciliationResult(
        "C001", Decimal(expected), Decimal(paid), Decimal(outstanding),
        Decimal(paid) - Decimal(expected), status, 0, 0, 0,
    )


@pytest.mark.parametrize(
    "status", [ReconciliationStatus.READY_TO_PAY, ReconciliationStatus.UNDERPAID]
)
def test_payment_eligible_reconciliation_creates_outstanding_obligation(status):
    result = reconciliation(status, paid="50.00", outstanding="195.00")
    item = create_payout_obligation(result, "2026-01")
    assert item.obligation_id == "OBL-2026-01-C001"
    assert item.creator_id == "C001"
    assert item.payout_cycle_id == "2026-01"
    assert item.expected_payout == Decimal("245.00")
    assert item.previously_paid_amount == Decimal("50.00")
    assert item.outstanding_amount == Decimal("195.00")
    assert item.reconciliation_status is status
    assert item.status is ObligationStatus.OUTSTANDING


@pytest.mark.parametrize(
    "status",
    [
        ReconciliationStatus.PAID,
        ReconciliationStatus.OVERPAID,
        ReconciliationStatus.INVALID_RECORD,
    ],
)
def test_non_payable_reconciliation_cannot_create_obligation(status):
    with pytest.raises(ObligationCreationError, match="cannot create"):
        create_payout_obligation(reconciliation(status), "2026-01")


@pytest.mark.parametrize("balance", ["0.00", "-1.00"])
def test_non_positive_reconciliation_balance_cannot_create_obligation(balance):
    with pytest.raises(ObligationCreationError, match="greater than zero"):
        create_payout_obligation(reconciliation(outstanding=balance), "2026-01")


def test_approval_references_and_approves_the_correct_obligation():
    item = create_payout_obligation(reconciliation(), "2026-01")
    approved, approval = record_approval_decision(
        item,
        approval_id="APR-000001",
        decision=ApprovalDecision.APPROVED,
        approved_by="finance-reviewer",
        approved_at=APPROVED_AT,
    )
    assert approval.obligation_id == item.obligation_id
    assert approval.approved_by == "finance-reviewer"
    assert approval.approved_at == APPROVED_AT
    assert approved.status is ObligationStatus.APPROVED
    assert item.status is ObligationStatus.OUTSTANDING


def test_rejection_transitions_obligation_to_rejected():
    item = create_payout_obligation(reconciliation(), "2026-01")
    rejected, approval = record_approval_decision(
        item,
        approval_id="APR-000002",
        decision=ApprovalDecision.REJECTED,
        approved_by="finance-reviewer",
        approved_at=APPROVED_AT,
    )
    assert approval.decision is ApprovalDecision.REJECTED
    assert rejected.status is ObligationStatus.REJECTED


def test_decided_obligation_cannot_transition_again():
    item = create_payout_obligation(reconciliation(), "2026-01")
    approved, _ = record_approval_decision(
        item,
        approval_id="APR-000001",
        decision=ApprovalDecision.APPROVED,
        approved_by="finance-reviewer",
        approved_at=APPROVED_AT,
    )
    with pytest.raises(ObligationTransitionError, match="Cannot decide"):
        record_approval_decision(
            approved,
            approval_id="APR-000002",
            decision=ApprovalDecision.REJECTED,
            approved_by="another-reviewer",
            approved_at=APPROVED_AT,
        )
