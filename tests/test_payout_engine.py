"""Tests for the V1 payout engine business rules."""

from datetime import date
from decimal import Decimal

from creator_payout_ops.models import CreatorAgreement, PlatformOrder, ReconciliationStatus, SettlementStatus
from creator_payout_ops.payout_engine import aggregate_creator_payouts, calculate_order_payout, calculate_payouts, find_effective_agreement


def order(order_id="O1", creator_id="C1", day=date(2026, 1, 15), commission="100.00", refund="0.00", status=SettlementStatus.SETTLED):
    return PlatformOrder(order_id, creator_id, "creator_a", day, Decimal("500.00"), Decimal(commission), Decimal(refund), status)


def agreement(rate="0.70", effective=date(2026, 1, 1), end=None, creator_id="C1"):
    return CreatorAgreement(creator_id, "Creator A", Decimal(rate), effective, end, True)


def test_settled_order_with_valid_agreement():
    result = calculate_order_payout(order(), [agreement()])
    assert result.status is ReconciliationStatus.ELIGIBLE
    assert result.expected_payout == Decimal("70.00")
    assert result.creator_share_rate == Decimal("0.70")


def test_effective_dated_agreement_before_and_after_rate_change():
    agreements = [agreement("0.70", end=date(2026, 6, 30)), agreement("0.75", date(2026, 7, 1))]
    before = calculate_order_payout(order(day=date(2026, 6, 28)), agreements)
    after = calculate_order_payout(order(day=date(2026, 7, 3)), agreements)
    assert before.expected_payout == Decimal("70.00")
    assert before.agreement_effective_date == date(2026, 1, 1)
    assert after.expected_payout == Decimal("75.00")
    assert after.agreement_effective_date == date(2026, 7, 1)
    assert find_effective_agreement(order(day=date(2026, 7, 3)), agreements) == agreements[1]


def test_missing_agreement():
    assert calculate_order_payout(order(), []).status is ReconciliationStatus.MISSING_AGREEMENT


def test_overlapping_agreements_are_invalid():
    result = calculate_order_payout(order(), [agreement("0.70"), agreement("0.75")])
    assert result.status is ReconciliationStatus.INVALID_AGREEMENT
    assert result.expected_payout == Decimal("0.00")


def test_pending_settlement():
    result = calculate_order_payout(order(status=SettlementStatus.PENDING), [agreement()])
    assert result.status is ReconciliationStatus.PENDING_SETTLEMENT
    assert result.expected_payout == Decimal("0.00")


def test_cancelled_order():
    result = calculate_order_payout(order(status=SettlementStatus.CANCELLED), [agreement()])
    assert result.status is ReconciliationStatus.CANCELLED
    assert result.expected_payout == Decimal("0.00")


def test_refunded_order():
    result = calculate_order_payout(order(status=SettlementStatus.REFUNDED), [agreement()])
    assert result.status is ReconciliationStatus.REFUNDED
    assert result.expected_payout == Decimal("0.00")


def test_every_duplicate_occurrence_is_returned_and_flagged():
    results = calculate_payouts([order("DUP"), order("DUP")], [agreement()])
    assert len(results) == 2
    assert all(result.status is ReconciliationStatus.DUPLICATE_ORDER for result in results)


def test_decimal_calculation_rounds_half_up_to_two_places():
    result = calculate_order_payout(order(commission="10.01"), [agreement("0.625")])
    assert result.expected_payout == Decimal("6.26")


def test_refund_amount_is_not_deducted_again():
    result = calculate_order_payout(order(commission="100.00", refund="80.00"), [agreement("0.70")])
    assert result.expected_payout == Decimal("70.00")


def test_invalid_order_does_not_calculate():
    result = calculate_order_payout(order(commission="-1.00"), [agreement()])
    assert result.status is ReconciliationStatus.INVALID_RECORD
    assert result.expected_payout == Decimal("0.00")


def test_invalid_agreement_rate_does_not_calculate():
    result = calculate_order_payout(order(), [agreement("1.20")])
    assert result.status is ReconciliationStatus.INVALID_AGREEMENT


def test_creator_level_payout_aggregation_excludes_ineligible_results():
    results = calculate_payouts([
        order("O1", "C1", commission="100.00"),
        order("O2", "C1", commission="50.00"),
        order("O3", "C2", commission="20.00"),
        order("O4", "C1", commission="90.00", status=SettlementStatus.PENDING),
    ], [agreement("0.70", creator_id="C1"), agreement("0.50", creator_id="C2")])
    summaries = aggregate_creator_payouts(results)
    assert [(s.creator_id, s.eligible_order_count, s.expected_payout) for s in summaries] == [
        ("C1", 2, Decimal("105.00")),
        ("C2", 1, Decimal("10.00")),
    ]
