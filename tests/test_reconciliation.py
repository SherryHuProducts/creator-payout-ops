"""Tests for creator-level payout reconciliation."""

from datetime import date
from decimal import Decimal

from creator_payout_ops.models import (
    CreatorPayoutSummary,
    PaymentRecord,
    PaymentStatus,
    ReconciliationStatus,
)
from creator_payout_ops.reconciliation import reconcile_creator_payout, reconcile_payouts


def summary(expected="100.00", creator_id="C1"):
    return CreatorPayoutSummary(creator_id, 1, Decimal(expected))


def payment(amount, status=PaymentStatus.PAID, creator_id="C1", payment_id="P1"):
    return PaymentRecord(
        payment_id,
        creator_id,
        date(2026, 1, 31),
        Decimal(amount),
        status,
        None,
    )


def test_no_historical_payment_is_ready_to_pay():
    result = reconcile_creator_payout(summary(), [])
    assert result.status is ReconciliationStatus.READY_TO_PAY
    assert result.amount_paid == Decimal("0.00")
    assert result.difference == Decimal("100.00")


def test_exact_payment_is_paid():
    result = reconcile_creator_payout(summary(), [payment("100.00")])
    assert result.status is ReconciliationStatus.PAID
    assert result.difference == Decimal("0.00")
    assert result.paid_payment_count == 1


def test_partial_payment_is_underpaid():
    result = reconcile_creator_payout(summary(), [payment("40.00")])
    assert result.status is ReconciliationStatus.UNDERPAID
    assert result.difference == Decimal("60.00")


def test_excess_payment_is_overpaid():
    result = reconcile_creator_payout(summary(), [payment("125.00")])
    assert result.status is ReconciliationStatus.OVERPAID
    assert result.difference == Decimal("-25.00")


def test_failed_payment_is_counted_but_not_paid():
    result = reconcile_creator_payout(
        summary(), [payment("100.00", PaymentStatus.FAILED)]
    )
    assert result.status is ReconciliationStatus.READY_TO_PAY
    assert result.amount_paid == Decimal("0.00")
    assert result.failed_payment_count == 1
    assert result.paid_payment_count == 0


def test_pending_payment_is_counted_but_not_paid():
    result = reconcile_creator_payout(
        summary(), [payment("100.00", PaymentStatus.PENDING)]
    )
    assert result.status is ReconciliationStatus.READY_TO_PAY
    assert result.amount_paid == Decimal("0.00")
    assert result.pending_payment_count == 1


def test_multiple_paid_payments_are_summed():
    result = reconcile_creator_payout(
        summary(), [payment("40.00", payment_id="P1"), payment("60.00", payment_id="P2")]
    )
    assert result.status is ReconciliationStatus.PAID
    assert result.amount_paid == Decimal("100.00")
    assert result.paid_payment_count == 2


def test_decimal_precision_and_currency_quantization():
    result = reconcile_creator_payout(
        summary("10.005"), [payment("3.333"), payment("3.333", payment_id="P2")]
    )
    assert result.expected_payout == Decimal("10.01")
    assert result.amount_paid == Decimal("6.67")
    assert result.difference == Decimal("3.34")
    assert result.status is ReconciliationStatus.UNDERPAID


def test_zero_expected_and_zero_paid_is_paid():
    assert reconcile_creator_payout(summary("0.00"), []).status is ReconciliationStatus.PAID


def test_batch_reconciliation_groups_by_creator_and_preserves_summary_order():
    summaries = [summary("100.00", "C1"), summary("50.00", "C2"), summary("20.00", "C3")]
    payments = [
        payment("100.00", creator_id="C1"),
        payment("10.00", creator_id="C2", payment_id="P2"),
        payment("999.00", creator_id="UNRELATED", payment_id="P3"),
    ]
    results = reconcile_payouts(summaries, payments)
    assert [result.creator_id for result in results] == ["C1", "C2", "C3"]
    assert [result.status for result in results] == [
        ReconciliationStatus.PAID,
        ReconciliationStatus.UNDERPAID,
        ReconciliationStatus.READY_TO_PAY,
    ]
