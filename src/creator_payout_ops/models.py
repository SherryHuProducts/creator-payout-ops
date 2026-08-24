"""Canonical data models for creator payout operations.

All financial values and rates are represented by :class:`~decimal.Decimal`.
Only settled transactions will eventually be eligible for payout.  The
``actual_commission`` value is the platform's final commission amount, so V1
must not subtract ``refund_amount`` from it again.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional


class SettlementStatus(str, Enum):
    SETTLED = "SETTLED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class ReconciliationStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    READY_TO_PAY = "READY_TO_PAY"
    PAID = "PAID"
    UNDERPAID = "UNDERPAID"
    OVERPAID = "OVERPAID"
    PENDING_SETTLEMENT = "PENDING_SETTLEMENT"
    MISSING_AGREEMENT = "MISSING_AGREEMENT"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    INVALID_RECORD = "INVALID_RECORD"
    INVALID_AGREEMENT = "INVALID_AGREEMENT"


@dataclass(frozen=True)
class PlatformOrder:
    order_id: str
    creator_id: str
    creator_username: str
    order_date: date
    gross_sales: Decimal
    actual_commission: Decimal
    refund_amount: Decimal
    settlement_status: SettlementStatus


@dataclass(frozen=True)
class CreatorAgreement:
    """Agreement whose future selection uses order date and effective range."""

    creator_id: str
    creator_name: str
    creator_share_rate: Decimal
    effective_date: date
    end_date: Optional[date]
    active: bool


@dataclass(frozen=True)
class PaymentRecord:
    """Historical payment.

    Only PAID records count toward already-paid amounts; FAILED and PENDING
    records are not completed payments.
    """

    payment_id: str
    creator_id: str
    payment_date: date
    amount_paid: Decimal
    payment_status: PaymentStatus
    provider_reference: Optional[str]


@dataclass(frozen=True)
class PayoutResult:
    """The payout engine's decision for one platform order."""

    order_id: str
    creator_id: str
    order_date: date
    actual_commission: Decimal
    creator_share_rate: Optional[Decimal]
    expected_payout: Decimal
    status: ReconciliationStatus
    agreement_effective_date: Optional[date]
    reason: Optional[str]


@dataclass(frozen=True)
class CreatorPayoutSummary:
    """Eligible order payouts aggregated for one creator."""

    creator_id: str
    eligible_order_count: int
    expected_payout: Decimal


@dataclass(frozen=True)
class CreatorReconciliationResult:
    """Comparison of one creator's expected payout and completed payments."""

    creator_id: str
    expected_payout: Decimal
    amount_paid: Decimal
    outstanding_balance: Decimal
    variance: Decimal
    status: ReconciliationStatus
    paid_payment_count: int
    pending_payment_count: int
    failed_payment_count: int
