"""HTTP request and response contracts for the portfolio API."""

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..models import PaymentFailureType, WebhookEventType

Money = Annotated[
    str,
    Field(
        pattern=r"^-?\d+\.\d{2}$",
        description="Fixed two-decimal monetary string; never a JSON float.",
        examples=["92.73"],
    ),
]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReconcileRequest(APIModel):
    payout_cycle_id: str = Field(min_length=1, examples=["2025-Q3"])
    creator_id: str = Field(min_length=1, examples=["CR-D"])


class ObligationResponse(APIModel):
    obligation_id: str
    creator_id: str
    payout_cycle_id: str
    expected_payout: Money
    previously_paid: Money
    outstanding: Money
    reconciliation_status: str
    obligation_status: str


class ApprovalRequest(APIModel):
    approval_id: str = Field(min_length=1, examples=["APR-DEMO-0001"])
    approved_by: str = Field(min_length=1, examples=["demo-finance-reviewer"])


class ApprovalResponse(APIModel):
    approval_id: str
    obligation_id: str
    decision: str
    approved_by: str
    approved_at: datetime
    obligation_status: str


class PaymentResponse(APIModel):
    payment_attempt_id: str
    obligation_id: str
    amount: Money
    currency: str
    status: str
    provider_reference: str | None
    idempotency_key: str


class WebhookRequest(APIModel):
    event_id: str = Field(min_length=1, examples=["EVT-DEMO-0001"])
    event_type: WebhookEventType = Field(
        examples=[WebhookEventType.PAYMENT_SUCCEEDED]
    )
    provider_payment_id: str = Field(min_length=1, examples=["PROV-000001"])
    payment_date: date = Field(examples=["2025-09-30"])
    failure_type: PaymentFailureType | None = None
    failure_reason: str | None = None


class WebhookResponse(APIModel):
    event_id: str
    provider_payment_id: str
    processing_status: str
    previous_payment_status: str | None
    new_payment_status: str | None
    message: str


class ApprovalView(APIModel):
    approval_id: str
    decision: str
    approved_by: str
    approved_at: datetime


class ConfirmedPaymentView(APIModel):
    payment_id: str
    payment_date: date
    amount: Money
    status: str
    provider_reference: str | None


class ReconciliationView(APIModel):
    expected_payout: Money
    amount_paid: Money
    outstanding: Money
    status: str


class AuditSummary(APIModel):
    approval_records: int
    payment_attempts: int
    webhook_events: int
    confirmed_payments: int


class ObligationLifecycleResponse(APIModel):
    lifecycle_status: str
    obligation: ObligationResponse
    approval: ApprovalView | None
    latest_payment: PaymentResponse | None
    confirmed_payment: ConfirmedPaymentView | None
    final_reconciliation: ReconciliationView
    audit_trail: AuditSummary
