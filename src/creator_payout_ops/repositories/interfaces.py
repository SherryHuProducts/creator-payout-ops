"""Repository protocols for future persistence adapters.

These ports use the existing domain models and deliberately make no database
or framework assumptions.
"""

from typing import Protocol

from ..models import (
    CreatorAgreement,
    PaymentAttempt,
    PaymentRecord,
    PayoutResult,
    PlatformOrder,
    WebhookEvent,
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


class WebhookEventRepository(Protocol):
    """Track webhook events for event-id idempotency."""

    def has_processed(self, event_id: str) -> bool: ...

    def mark_processed(self, event: WebhookEvent) -> None: ...
