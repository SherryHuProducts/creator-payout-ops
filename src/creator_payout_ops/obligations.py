"""Creation and authorization of payout obligations."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from .models import (
    ApprovalDecision,
    ApprovalRecord,
    CreatorReconciliationResult,
    ObligationStatus,
    PayoutObligation,
    ReconciliationStatus,
)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
PAYABLE_RECONCILIATION_STATUSES = frozenset(
    {ReconciliationStatus.READY_TO_PAY, ReconciliationStatus.UNDERPAID}
)


class ObligationCreationError(ValueError):
    """A reconciliation result cannot create a payable obligation."""


class ObligationTransitionError(ValueError):
    """An obligation approval transition is invalid."""


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def build_obligation_id(creator_id: str, payout_cycle_id: str) -> str:
    """Return the stable business identity for one creator payout cycle."""

    creator = creator_id.strip()
    cycle = payout_cycle_id.strip()
    if not creator or not cycle:
        raise ObligationCreationError("creator_id and payout_cycle_id are required")
    return f"OBL-{cycle}-{creator}"


def create_payout_obligation(
    reconciliation_result: CreatorReconciliationResult,
    payout_cycle_id: str,
) -> PayoutObligation:
    """Create an outstanding obligation from a payment-eligible reconciliation."""

    if reconciliation_result.status not in PAYABLE_RECONCILIATION_STATUSES:
        raise ObligationCreationError(
            f"Reconciliation status {reconciliation_result.status.value} "
            "cannot create a payout obligation"
        )
    outstanding = _money(reconciliation_result.outstanding_balance)
    if outstanding <= ZERO:
        raise ObligationCreationError("Outstanding amount must be greater than zero")

    cycle = payout_cycle_id.strip()
    return PayoutObligation(
        obligation_id=build_obligation_id(reconciliation_result.creator_id, cycle),
        creator_id=reconciliation_result.creator_id,
        payout_cycle_id=cycle,
        expected_payout=_money(reconciliation_result.expected_payout),
        previously_paid_amount=_money(reconciliation_result.amount_paid),
        outstanding_amount=outstanding,
        reconciliation_status=reconciliation_result.status,
        status=ObligationStatus.OUTSTANDING,
    )


def record_approval_decision(
    obligation: PayoutObligation,
    *,
    approval_id: str,
    decision: ApprovalDecision,
    approved_by: str,
    approved_at: datetime,
) -> tuple[PayoutObligation, ApprovalRecord]:
    """Record the sole approval decision for an outstanding obligation."""

    if obligation.status is not ObligationStatus.OUTSTANDING:
        raise ObligationTransitionError(
            f"Cannot decide obligation in {obligation.status.value} status"
        )
    if not approval_id.strip() or not approved_by.strip():
        raise ObligationTransitionError("approval_id and approved_by are required")

    status = (
        ObligationStatus.APPROVED
        if decision is ApprovalDecision.APPROVED
        else ObligationStatus.REJECTED
    )
    approval = ApprovalRecord(
        approval_id=approval_id.strip(),
        obligation_id=obligation.obligation_id,
        decision=decision,
        approved_by=approved_by.strip(),
        approved_at=approved_at,
    )
    return replace(obligation, status=status), approval
