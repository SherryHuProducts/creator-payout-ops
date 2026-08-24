"""Structured validation for canonical payout records."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Iterable

from .models import CreatorAgreement, PaymentRecord, PaymentStatus, PlatformOrder, SettlementStatus


@dataclass(frozen=True)
class ValidationIssue:
    record_type: str
    record_id: str
    field: str
    issue_type: str
    message: str


def _issue(record_type: str, record_id: str, field: str, kind: str, message: str) -> ValidationIssue:
    return ValidationIssue(record_type, record_id, field, kind, message)


def _valid_enum(value: object, enum_type: type[Enum]) -> bool:
    try:
        enum_type(value if isinstance(value, str) else value.value)
        return True
    except (ValueError, AttributeError):
        return False


def validate_platform_orders(records: Iterable[PlatformOrder]) -> list[ValidationIssue]:
    issues, seen = [], set()
    for record in records:
        rid = record.order_id
        if not rid.strip():
            issues.append(_issue("platform_order", rid, "order_id", "missing_required_id", "order_id is required"))
        elif rid in seen:
            issues.append(_issue("platform_order", rid, "order_id", "duplicate_order_id", f"Duplicate order_id: {rid}"))
        seen.add(rid)
        if not record.creator_id.strip():
            issues.append(_issue("platform_order", rid, "creator_id", "missing_required_id", "creator_id is required"))
        for field in ("gross_sales", "actual_commission"):
            if getattr(record, field) < Decimal("0"):
                issues.append(_issue("platform_order", rid, field, "negative_value", f"{field} cannot be negative"))
        if not _valid_enum(record.settlement_status, SettlementStatus):
            issues.append(_issue("platform_order", rid, "settlement_status", "invalid_status", "Invalid settlement status"))
    return issues


def validate_creator_agreements(records: Iterable[CreatorAgreement]) -> list[ValidationIssue]:
    issues = []
    for record in records:
        rid = record.creator_id
        if not rid.strip():
            issues.append(_issue("creator_agreement", rid, "creator_id", "missing_required_id", "creator_id is required"))
        if not Decimal("0") <= record.creator_share_rate <= Decimal("1"):
            issues.append(_issue("creator_agreement", rid, "creator_share_rate", "out_of_range", "creator_share_rate must be between 0 and 1"))
        if record.end_date is not None and record.end_date < record.effective_date:
            issues.append(_issue("creator_agreement", rid, "end_date", "invalid_date_range", "end_date cannot be earlier than effective_date"))
    return issues


def validate_payment_records(records: Iterable[PaymentRecord]) -> list[ValidationIssue]:
    issues = []
    for record in records:
        rid = record.payment_id
        if not rid.strip():
            issues.append(_issue("payment_record", rid, "payment_id", "missing_required_id", "payment_id is required"))
        if not record.creator_id.strip():
            issues.append(_issue("payment_record", rid, "creator_id", "missing_required_id", "creator_id is required"))
        if record.amount_paid <= Decimal("0"):
            issues.append(_issue("payment_record", rid, "amount_paid", "non_positive_value", "amount_paid must be greater than zero"))
        if not _valid_enum(record.payment_status, PaymentStatus):
            issues.append(_issue("payment_record", rid, "payment_status", "invalid_status", "Invalid payment status"))
    return issues


def validate_all(orders: Iterable[PlatformOrder], agreements: Iterable[CreatorAgreement], payments: Iterable[PaymentRecord]) -> list[ValidationIssue]:
    return validate_platform_orders(orders) + validate_creator_agreements(agreements) + validate_payment_records(payments)
