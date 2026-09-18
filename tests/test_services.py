"""Tests for the thin application service layer."""

from datetime import date
from decimal import Decimal

from creator_payout_ops.models import (
    CreatorAgreement,
    PaymentRecord,
    PaymentStatus,
    PlatformOrder,
    ReconciliationStatus,
    SettlementStatus,
)
from creator_payout_ops.services import PayoutService, ReconciliationService


def test_payout_service_delegates_calculation_and_aggregation():
    orders = [
        PlatformOrder(
            "O1",
            "C1",
            "creator_a",
            date(2026, 1, 15),
            Decimal("500.00"),
            Decimal("100.00"),
            Decimal("0.00"),
            SettlementStatus.SETTLED,
        )
    ]
    agreements = [
        CreatorAgreement(
            "C1", "Creator A", Decimal("0.70"), date(2026, 1, 1), None, True
        )
    ]

    service = PayoutService()
    results = service.calculate_payouts(orders, agreements)
    summaries = service.aggregate_creator_payouts(results)

    assert results[0].status is ReconciliationStatus.ELIGIBLE
    assert results[0].expected_payout == Decimal("70.00")
    assert summaries[0].expected_payout == Decimal("70.00")


def test_reconciliation_service_delegates_batch_reconciliation():
    payout_service = PayoutService()
    results = payout_service.calculate_payouts(
        [
            PlatformOrder(
                "O1",
                "C1",
                "creator_a",
                date(2026, 1, 15),
                Decimal("500.00"),
                Decimal("100.00"),
                Decimal("0.00"),
                SettlementStatus.SETTLED,
            )
        ],
        [
            CreatorAgreement(
                "C1", "Creator A", Decimal("0.70"), date(2026, 1, 1), None, True
            )
        ],
    )
    summaries = payout_service.aggregate_creator_payouts(results)
    payments = [
        PaymentRecord(
            "P1",
            "C1",
            date(2026, 1, 31),
            Decimal("70.00"),
            PaymentStatus.PAID,
            "provider-1",
        )
    ]

    reconciliations = ReconciliationService().reconcile_payouts(summaries, payments)

    assert len(reconciliations) == 1
    assert reconciliations[0].status is ReconciliationStatus.PAID
    assert reconciliations[0].outstanding_balance == Decimal("0.00")
