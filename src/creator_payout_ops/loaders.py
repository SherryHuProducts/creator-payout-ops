"""Strict CSV loaders for canonical payout models."""

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import TypeVar

from .models import CreatorAgreement, PaymentRecord, PaymentStatus, PlatformOrder, SettlementStatus

E = TypeVar("E", bound=Enum)


class CSVLoadError(ValueError):
    """A CSV field could not be converted into its canonical representation."""


def _required(row: dict[str, str | None], field: str, path: Path, line: int) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise CSVLoadError(f"{path}:{line}: required field '{field}' is blank")
    return value


def _date(value: str, field: str, path: Path, line: int) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CSVLoadError(f"{path}:{line}: invalid {field} date {value!r}; expected YYYY-MM-DD") from exc


def _decimal(value: str, field: str, path: Path, line: int) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise CSVLoadError(f"{path}:{line}: invalid decimal for {field}: {value!r}") from exc


def _enum(value: str, enum_type: type[E], field: str, path: Path, line: int) -> E:
    try:
        return enum_type(value.strip().upper())
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise CSVLoadError(f"{path}:{line}: invalid {field} {value!r}; expected one of: {allowed}") from exc


def _bool(value: str, field: str, path: Path, line: int) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise CSVLoadError(f"{path}:{line}: invalid boolean for {field}: {value!r}")


def _rows(path: str | Path):
    source = Path(path)
    try:
        handle = source.open(newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise CSVLoadError(f"Unable to read CSV {source}: {exc}") from exc
    with handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise CSVLoadError(f"{source}: missing header row")
        for line, row in enumerate(reader, start=2):
            yield source, line, row


def load_platform_orders(path: str | Path) -> list[PlatformOrder]:
    result = []
    for source, line, row in _rows(path):
        req = lambda field: _required(row, field, source, line)
        result.append(PlatformOrder(req("order_id"), req("creator_id"), req("creator_username"),
            _date(req("order_date"), "order_date", source, line),
            _decimal(req("gross_sales"), "gross_sales", source, line),
            _decimal(req("actual_commission"), "actual_commission", source, line),
            _decimal(req("refund_amount"), "refund_amount", source, line),
            _enum(req("settlement_status"), SettlementStatus, "settlement_status", source, line)))
    return result


def load_creator_agreements(path: str | Path) -> list[CreatorAgreement]:
    result = []
    for source, line, row in _rows(path):
        req = lambda field: _required(row, field, source, line)
        end = (row.get("end_date") or "").strip()
        result.append(CreatorAgreement(req("creator_id"), req("creator_name"),
            _decimal(req("creator_share_rate"), "creator_share_rate", source, line),
            _date(req("effective_date"), "effective_date", source, line),
            _date(end, "end_date", source, line) if end else None,
            _bool(req("active"), "active", source, line)))
    return result


def load_payment_records(path: str | Path) -> list[PaymentRecord]:
    result = []
    for source, line, row in _rows(path):
        req = lambda field: _required(row, field, source, line)
        reference = (row.get("provider_reference") or "").strip() or None
        result.append(PaymentRecord(req("payment_id"), req("creator_id"),
            _date(req("payment_date"), "payment_date", source, line),
            _decimal(req("amount_paid"), "amount_paid", source, line),
            _enum(req("payment_status"), PaymentStatus, "payment_status", source, line), reference))
    return result
