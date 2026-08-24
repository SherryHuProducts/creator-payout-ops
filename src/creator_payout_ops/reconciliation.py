"""Creator-level reconciliation of expected payouts and payment history.

Only historical payments whose status is ``PAID`` count toward the amount
already paid. ``PENDING`` and ``FAILED`` records are tracked but are not
completed payments. No payment execution occurs in this module.
"""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from .models import (
    CreatorPayoutSummary,
    CreatorReconciliationResult,
    PaymentRecord,
    PaymentStatus,
    ReconciliationStatus,
)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _currency(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def reconcile_creator_payout(
    payout_summary: CreatorPayoutSummary,
    payment_records: list[PaymentRecord],
) -> CreatorReconciliationResult:
    """Reconcile one creator summary against that creator's payment records."""

    creator_payments = [
        payment
        for payment in payment_records
        if payment.creator_id == payout_summary.creator_id
    ]
    paid_payments = [
        payment
        for payment in creator_payments
        if payment.payment_status is PaymentStatus.PAID
    ]
    paid = _currency(sum((payment.amount_paid for payment in paid_payments), ZERO))
    expected = _currency(payout_summary.expected_payout)
    outstanding_balance = _currency(expected - paid)
    variance = _currency(paid - expected)

    # A pending payment is intentionally not treated as completed here. The
    # future payment execution layer must prevent initiating a second payment
    # while an active PENDING payment exists; that safety control does not
    # belong to reconciliation.
    if expected == paid:
        status = ReconciliationStatus.PAID
    elif expected > ZERO and paid == ZERO:
        status = ReconciliationStatus.READY_TO_PAY
    elif ZERO < paid < expected:
        status = ReconciliationStatus.UNDERPAID
    elif paid > expected:
        status = ReconciliationStatus.OVERPAID
    else:
        # Creator payout summaries are non-negative by construction. Keeping a
        # defensive status makes malformed direct input explicit.
        status = ReconciliationStatus.INVALID_RECORD

    return CreatorReconciliationResult(
        creator_id=payout_summary.creator_id,
        expected_payout=expected,
        amount_paid=paid,
        outstanding_balance=outstanding_balance,
        variance=variance,
        status=status,
        paid_payment_count=len(paid_payments),
        pending_payment_count=sum(
            payment.payment_status is PaymentStatus.PENDING
            for payment in creator_payments
        ),
        failed_payment_count=sum(
            payment.payment_status is PaymentStatus.FAILED
            for payment in creator_payments
        ),
    )


def reconcile_payouts(
    payout_summaries: list[CreatorPayoutSummary],
    payment_records: list[PaymentRecord],
) -> list[CreatorReconciliationResult]:
    """Return one reconciliation result per creator payout summary."""

    payments_by_creator: dict[str, list[PaymentRecord]] = defaultdict(list)
    for payment in payment_records:
        payments_by_creator[payment.creator_id].append(payment)
    return [
        reconcile_creator_payout(
            summary, payments_by_creator.get(summary.creator_id, [])
        )
        for summary in payout_summaries
    ]
