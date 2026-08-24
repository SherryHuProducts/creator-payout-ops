"""Order-level expected payout calculation.

This module determines how much *should* be paid. It intentionally does not
inspect historical payments or perform reconciliation or payment execution.
All financial arithmetic uses :class:`decimal.Decimal`.
"""

from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

from .models import (
    CreatorAgreement,
    CreatorPayoutSummary,
    PayoutResult,
    PlatformOrder,
    ReconciliationStatus,
    SettlementStatus,
)
from .validators import validate_creator_agreements, validate_platform_orders

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def _matching_agreements(
    order: PlatformOrder, agreements: list[CreatorAgreement]
) -> list[CreatorAgreement]:
    return [
        agreement
        for agreement in agreements
        if agreement.creator_id == order.creator_id
        and agreement.active
        and agreement.effective_date <= order.order_date
        and (agreement.end_date is None or order.order_date <= agreement.end_date)
    ]


def find_effective_agreement(
    order: PlatformOrder, agreements: list[CreatorAgreement]
) -> CreatorAgreement | None:
    """Return the sole agreement effective on ``order_date``.

    ``None`` represents either zero or multiple matches. Callers that need to
    classify that distinction should inspect the matching set, as the payout
    calculation does below.
    """

    matches = _matching_agreements(order, agreements)
    return matches[0] if len(matches) == 1 else None


def _result(
    order: PlatformOrder,
    status: ReconciliationStatus,
    reason: str | None,
    *,
    agreement: CreatorAgreement | None = None,
    expected_payout: Decimal = ZERO,
) -> PayoutResult:
    return PayoutResult(
        order_id=order.order_id,
        creator_id=order.creator_id,
        order_date=order.order_date,
        actual_commission=order.actual_commission,
        creator_share_rate=(agreement.creator_share_rate if agreement else None),
        expected_payout=expected_payout,
        status=status,
        agreement_effective_date=(agreement.effective_date if agreement else None),
        reason=reason,
    )


def calculate_order_payout(
    order: PlatformOrder,
    agreements: list[CreatorAgreement],
    duplicate_order_ids: set[str] | None = None,
) -> PayoutResult:
    """Apply V1 business rules to one order in their required precedence."""

    order_issues = [
        issue
        for issue in validate_platform_orders([order])
        if issue.issue_type != "duplicate_order_id"
    ]
    if order_issues:
        return _result(
            order,
            ReconciliationStatus.INVALID_RECORD,
            "; ".join(issue.message for issue in order_issues),
        )

    if duplicate_order_ids and order.order_id in duplicate_order_ids:
        return _result(
            order, ReconciliationStatus.DUPLICATE_ORDER, "Duplicate order_id requires review"
        )

    if order.settlement_status is SettlementStatus.PENDING:
        return _result(
            order, ReconciliationStatus.PENDING_SETTLEMENT, "Order is not yet settled"
        )
    if order.settlement_status is SettlementStatus.CANCELLED:
        return _result(
            order, ReconciliationStatus.CANCELLED, "Cancelled order is excluded from payout"
        )
    if order.settlement_status is SettlementStatus.REFUNDED:
        return _result(
            order, ReconciliationStatus.REFUNDED, "Refunded order is excluded from new payout"
        )

    matches = _matching_agreements(order, agreements)
    if not matches:
        return _result(
            order, ReconciliationStatus.MISSING_AGREEMENT, "No active agreement was effective on order_date"
        )
    if len(matches) > 1:
        return _result(
            order, ReconciliationStatus.INVALID_AGREEMENT, "Multiple agreements were effective on order_date"
        )

    agreement = matches[0]
    agreement_issues = validate_creator_agreements([agreement])
    if agreement_issues:
        return _result(
            order,
            ReconciliationStatus.INVALID_AGREEMENT,
            "; ".join(issue.message for issue in agreement_issues),
            agreement=agreement,
        )

    # actual_commission is final; refund_amount must not be deducted again.
    expected = (order.actual_commission * agreement.creator_share_rate).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    return _result(
        order,
        ReconciliationStatus.ELIGIBLE,
        None,
        agreement=agreement,
        expected_payout=expected,
    )


def calculate_payouts(
    orders: list[PlatformOrder], agreements: list[CreatorAgreement]
) -> list[PayoutResult]:
    """Calculate one result per input order, preserving duplicates."""

    counts = Counter(order.order_id for order in orders)
    duplicates = {order_id for order_id, count in counts.items() if count > 1}
    return [calculate_order_payout(order, agreements, duplicates) for order in orders]


def aggregate_creator_payouts(
    payout_results: list[PayoutResult],
) -> list[CreatorPayoutSummary]:
    """Aggregate only successfully eligible order-level payouts by creator."""

    totals: dict[str, tuple[int, Decimal]] = {}
    for result in payout_results:
        if result.status is not ReconciliationStatus.ELIGIBLE:
            continue
        count, amount = totals.get(result.creator_id, (0, ZERO))
        totals[result.creator_id] = (count + 1, amount + result.expected_payout)
    return [
        CreatorPayoutSummary(creator_id, count, amount.quantize(CENT))
        for creator_id, (count, amount) in sorted(totals.items())
    ]
