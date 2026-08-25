"""Tests for deterministic operational CSV reports."""

import csv
from datetime import date
from decimal import Decimal

from creator_payout_ops.models import (
    CreatorPayoutSummary,
    CreatorReconciliationResult,
    PayoutResult,
    ReconciliationStatus,
)
from creator_payout_ops.reports import (
    write_exception_report,
    write_payout_summary,
    write_reconciliation_report,
)
from creator_payout_ops.validators import ValidationIssue


def rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def payout(order_id, status, creator_id="C1", reason=None):
    return PayoutResult(
        order_id, creator_id, date(2025, 1, 1), Decimal("10.00"),
        Decimal("0.70"), Decimal("7.00"), status, date(2025, 1, 1), reason,
    )


def test_payout_summary_created_with_header_values_and_creator_order(tmp_path):
    path = tmp_path / "nested" / "payout.csv"
    write_payout_summary(
        [CreatorPayoutSummary("C2", 1, Decimal("2")), CreatorPayoutSummary("C1", 3, Decimal("10.5"))],
        path,
    )
    assert path.read_text().splitlines()[0] == "creator_id,eligible_order_count,expected_payout"
    assert rows(path) == [
        {"creator_id": "C1", "eligible_order_count": "3", "expected_payout": "10.50"},
        {"creator_id": "C2", "eligible_order_count": "1", "expected_payout": "2.00"},
    ]


def test_reconciliation_report_serializes_status_and_money(tmp_path):
    path = tmp_path / "reconciliation.csv"
    result = CreatorReconciliationResult(
        "C1", Decimal("10.5"), Decimal("2"), Decimal("8.5"), Decimal("-8.5"),
        ReconciliationStatus.UNDERPAID, 1, 2, 3,
    )
    write_reconciliation_report([result], path)
    assert path.exists()
    row = rows(path)[0]
    assert row["status"] == "UNDERPAID"
    assert [row[field] for field in ("expected_payout", "amount_paid", "outstanding_balance", "variance")] == ["10.50", "2.00", "8.50", "-8.50"]


def test_exception_report_combines_exceptions_and_excludes_eligible(tmp_path):
    path = tmp_path / "exceptions.csv"
    issues = [ValidationIssue("platform_order", "O1", "order_id", "duplicate_order_id", "Duplicate order")]
    payouts = [
        payout("O1", ReconciliationStatus.DUPLICATE_ORDER, reason="Duplicate payout"),
        payout("O2", ReconciliationStatus.MISSING_AGREEMENT, "C2", "No agreement"),
        payout("O3", ReconciliationStatus.ELIGIBLE, "C3"),
    ]
    write_exception_report(issues, payouts, path)
    report_rows = rows(path)
    assert path.exists()
    assert [(row["source"], row["record_id"]) for row in report_rows] == [
        ("VALIDATION", "O1"), ("PAYOUT", "O2")
    ]
    assert report_rows[0]["issue_type"] == "DUPLICATE_ORDER"
    assert all(row["record_id"] != "O3" for row in report_rows)


def test_report_rerun_overwrites_instead_of_appending(tmp_path):
    path = tmp_path / "payout.csv"
    write_payout_summary([CreatorPayoutSummary("C1", 1, Decimal("1"))], path)
    write_payout_summary([CreatorPayoutSummary("C2", 2, Decimal("2"))], path)
    assert [row["creator_id"] for row in rows(path)] == ["C2"]
