"""Deterministic CSV exports for finance and operations review."""

import csv
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .models import (
    CreatorPayoutSummary,
    CreatorReconciliationResult,
    PayoutResult,
    ReconciliationStatus,
)
from .validators import ValidationIssue

CENT = Decimal("0.01")


def _money(value: Decimal) -> str:
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), ".2f")


def _writer(output_path: Path | str, fieldnames: list[str]):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w", newline="", encoding="utf-8")
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    return handle, writer


def write_payout_summary(
    payout_summaries: list[CreatorPayoutSummary], output_path: Path | str
) -> None:
    """Write one calculated payout-obligation row per creator."""

    handle, writer = _writer(
        output_path, ["creator_id", "eligible_order_count", "expected_payout"]
    )
    with handle:
        for summary in sorted(payout_summaries, key=lambda item: item.creator_id):
            writer.writerow(
                {
                    "creator_id": summary.creator_id,
                    "eligible_order_count": summary.eligible_order_count,
                    "expected_payout": _money(summary.expected_payout),
                }
            )


def write_reconciliation_report(
    reconciliation_results: list[CreatorReconciliationResult],
    output_path: Path | str,
) -> None:
    """Write the initial historical-payment reconciliation by creator."""

    fields = [
        "creator_id",
        "expected_payout",
        "amount_paid",
        "outstanding_balance",
        "variance",
        "status",
        "paid_payment_count",
        "pending_payment_count",
        "failed_payment_count",
    ]
    handle, writer = _writer(output_path, fields)
    with handle:
        for result in sorted(reconciliation_results, key=lambda item: item.creator_id):
            writer.writerow(
                {
                    "creator_id": result.creator_id,
                    "expected_payout": _money(result.expected_payout),
                    "amount_paid": _money(result.amount_paid),
                    "outstanding_balance": _money(result.outstanding_balance),
                    "variance": _money(result.variance),
                    "status": result.status.value,
                    "paid_payment_count": result.paid_payment_count,
                    "pending_payment_count": result.pending_payment_count,
                    "failed_payment_count": result.failed_payment_count,
                }
            )


def _exception_category(issue_type: str) -> str:
    normalized = issue_type.upper()
    return "DUPLICATE_ORDER" if normalized == "DUPLICATE_ORDER_ID" else normalized


def write_exception_report(
    validation_issues: list[ValidationIssue],
    payout_results: list[PayoutResult],
    output_path: Path | str,
) -> None:
    """Combine input-validation and payout-processing exceptions.

    When validation and payout processing identify the same record/category,
    the validation row is retained and the redundant payout row is omitted.
    """

    fields = [
        "source", "record_type", "record_id", "creator_id", "status",
        "field", "issue_type", "message",
    ]
    exception_statuses = {
        ReconciliationStatus.DUPLICATE_ORDER,
        ReconciliationStatus.MISSING_AGREEMENT,
        ReconciliationStatus.INVALID_AGREEMENT,
        ReconciliationStatus.INVALID_RECORD,
    }
    creator_by_record = {result.order_id: result.creator_id for result in payout_results}
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    for issue in sorted(
        validation_issues,
        key=lambda item: (item.record_type, item.record_id, item.field, item.issue_type),
    ):
        category = _exception_category(issue.issue_type)
        key = (issue.record_id, category)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "source": "VALIDATION",
                "record_type": issue.record_type,
                "record_id": issue.record_id,
                "creator_id": creator_by_record.get(issue.record_id, ""),
                "status": "",
                "field": issue.field,
                "issue_type": category,
                "message": issue.message,
            }
        )

    for result in sorted(payout_results, key=lambda item: (item.order_id, item.creator_id)):
        if result.status not in exception_statuses:
            continue
        key = (result.order_id, result.status.value)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "source": "PAYOUT",
                "record_type": "platform_order",
                "record_id": result.order_id,
                "creator_id": result.creator_id,
                "status": result.status.value,
                "field": "",
                "issue_type": "",
                "message": result.reason or "Payout processing exception",
            }
        )

    handle, writer = _writer(output_path, fields)
    with handle:
        writer.writerows(rows)
