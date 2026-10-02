"""Webhook confirmation for provider payment events.

Payment-request idempotency prevents duplicate external payment creation.
Webhook event-id idempotency separately prevents an asynchronous provider
event from being applied more than once.
"""

from dataclasses import replace
from datetime import date

from .models import (
    PaymentAttempt,
    PaymentExecutionStatus,
    WebhookEvent,
    WebhookEventType,
    WebhookProcessingResult,
    WebhookProcessingStatus,
)
from .repositories.interfaces import WebhookEventRepository


def _result(
    event: WebhookEvent,
    processing_status: WebhookProcessingStatus,
    message: str,
    previous: PaymentExecutionStatus | None = None,
    new: PaymentExecutionStatus | None = None,
) -> WebhookProcessingResult:
    return WebhookProcessingResult(
        event.event_id,
        event.provider_payment_id,
        processing_status,
        previous,
        new,
        message,
    )


def transition_payment_attempt(
    event: WebhookEvent, attempt: PaymentAttempt
) -> tuple[WebhookProcessingResult, PaymentAttempt | None]:
    """Return the valid terminal transition without performing persistence."""

    previous = attempt.status
    if previous is not PaymentExecutionStatus.PENDING:
        return (
            _result(
                event,
                WebhookProcessingStatus.REJECTED,
                f"Invalid payment transition from {previous.value}",
                previous,
                previous,
            ),
            None,
        )

    if event.event_type is WebhookEventType.PAYMENT_SUCCEEDED:
        updated = replace(
            attempt,
            status=PaymentExecutionStatus.PAID,
            failure_type=None,
            failure_reason=None,
        )
    elif event.event_type is WebhookEventType.PAYMENT_FAILED:
        updated = replace(
            attempt,
            status=PaymentExecutionStatus.FAILED,
            failure_type=event.failure_type,
            failure_reason=event.failure_reason,
        )
    else:  # pragma: no cover - enums constrain normal callers
        return (
            _result(
                event,
                WebhookProcessingStatus.REJECTED,
                "Unsupported webhook event type",
                previous,
                previous,
            ),
            None,
        )

    return (
        _result(
            event,
            WebhookProcessingStatus.PROCESSED,
            f"Payment transitioned from {previous.value} to {updated.status.value}",
            previous,
            updated.status,
        ),
        updated,
    )


class WebhookHandler:
    """Apply valid provider events to existing pending payment attempts."""

    def __init__(self) -> None:
        self.processed_event_ids: set[str] = set()

    def process_event(
        self, event: WebhookEvent, payment_attempts: list[PaymentAttempt]
    ) -> WebhookProcessingResult:
        """Process one event, replacing—not mutating—the matching attempt.

        Terminal-state events with a new event ID are rejected rather than
        treated as successful no-ops. Rejected events are not marked processed.
        """

        if event.event_id in self.processed_event_ids:
            return _result(
                event,
                WebhookProcessingStatus.DUPLICATE,
                "Webhook event ID was already processed; no state change",
            )

        match = next(
            (
                (index, attempt)
                for index, attempt in enumerate(payment_attempts)
                if attempt.provider_payment_id == event.provider_payment_id
            ),
            None,
        )
        if match is None:
            return _result(
                event,
                WebhookProcessingStatus.REJECTED,
                "UNKNOWN_PROVIDER_PAYMENT",
            )

        index, attempt = match
        result, updated = transition_payment_attempt(event, attempt)
        if updated is None:
            return result
        payment_attempts[index] = updated
        self.processed_event_ids.add(event.event_id)
        return result


class PersistentWebhookHandler:
    """Apply webhook effects through an atomic durable repository boundary."""

    def __init__(self, repository: WebhookEventRepository) -> None:
        self.repository = repository

    def process_event(
        self, event: WebhookEvent, payment_date: date
    ) -> WebhookProcessingResult:
        return self.repository.process_webhook_event(event, payment_date)
