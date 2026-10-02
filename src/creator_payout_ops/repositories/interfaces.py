"""Repository protocols for persistence adapters.

These ports use the existing domain models and deliberately make no database
or framework assumptions.
"""

from datetime import date
from typing import Protocol

from ..models import (
    ApprovalRecord,
    CreatorAgreement,
    PaymentAttempt,
    PaymentRecord,
    PayoutAuditTrail,
    PayoutObligation,
    PayoutResult,
    PlatformOrder,
    WebhookEvent,
    WebhookProcessingResult,
)


class CreatorRepository(Protocol):
    """Load the creator agreements used by payout calculation."""

    def list_agreements(self) -> list[CreatorAgreement]: ...


class PayoutRepository(Protocol):
    """Load payout inputs and persist calculated payout decisions."""

    def list_orders(self) -> list[PlatformOrder]: ...

    def save_results(self, results: list[PayoutResult]) -> None: ...


class PaymentRepository(Protocol):
    """Access payment history and payment execution attempts."""

    def list_records(self) -> list[PaymentRecord]: ...

    def list_attempts(self, creator_id: str) -> list[PaymentAttempt]: ...

    def save_attempt(self, attempt: PaymentAttempt) -> None: ...

    def next_internal_payment_sequence(self) -> int: ...


class ObligationRepository(Protocol):
    """Persist payout obligations and their authorization decisions."""

    def save_obligation(self, obligation: PayoutObligation) -> None: ...

    def get_obligation(self, obligation_id: str) -> PayoutObligation | None: ...

    def save_approval(
        self, obligation: PayoutObligation, approval: ApprovalRecord
    ) -> None: ...

    def get_approval(self, obligation_id: str) -> ApprovalRecord | None: ...


class WebhookEventRepository(Protocol):
    """Track webhook events for event-id idempotency."""

    def has_processed(self, event_id: str) -> bool: ...

    def mark_processed(self, event: WebhookEvent) -> None: ...

    def process_webhook_event(
        self, event: WebhookEvent, payment_date: date
    ) -> WebhookProcessingResult: ...


class AuditTrailRepository(Protocol):
    """Reconstruct the persisted lifecycle for one payout obligation."""

    def get_audit_trail(self, obligation_id: str) -> PayoutAuditTrail: ...
