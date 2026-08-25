"""Tests for asynchronous payment confirmation."""

from decimal import Decimal

from creator_payout_ops.models import (
    PaymentAttempt,
    PaymentExecutionStatus,
    PaymentFailureType,
    WebhookEvent,
    WebhookEventType,
    WebhookProcessingStatus,
)
from creator_payout_ops.webhook_handler import WebhookHandler


def attempt(status=PaymentExecutionStatus.PENDING, failure_type=None, failure_reason=None):
    return PaymentAttempt(
        "PAY-000001", "C001", Decimal("245.00"), "USD", "key-1", status,
        "PROV-000001", failure_type, failure_reason, 1,
    )


def event(event_id="EVT-000001", event_type=WebhookEventType.PAYMENT_SUCCEEDED, provider_id="PROV-000001", failure_type=None, failure_reason=None):
    return WebhookEvent(event_id, event_type, provider_id, failure_type, failure_reason)


def test_pending_succeeded_transitions_to_paid_and_clears_failure_fields():
    attempts = [attempt(failure_type=PaymentFailureType.UNKNOWN, failure_reason="old")]
    original = attempts[0]
    result = WebhookHandler().process_event(event(), attempts)
    assert result.processing_status is WebhookProcessingStatus.PROCESSED
    assert result.previous_payment_status is PaymentExecutionStatus.PENDING
    assert result.new_payment_status is PaymentExecutionStatus.PAID
    assert attempts[0].status is PaymentExecutionStatus.PAID
    assert attempts[0].failure_type is None
    assert attempts[0].failure_reason is None
    assert original.status is PaymentExecutionStatus.PENDING


def test_pending_failed_transitions_and_stores_failure_details():
    attempts = [attempt()]
    failure = event(
        event_type=WebhookEventType.PAYMENT_FAILED,
        failure_type=PaymentFailureType.NON_RETRYABLE,
        failure_reason="Invalid recipient",
    )
    result = WebhookHandler().process_event(failure, attempts)
    assert result.new_payment_status is PaymentExecutionStatus.FAILED
    assert attempts[0].failure_type is PaymentFailureType.NON_RETRYABLE
    assert attempts[0].failure_reason == "Invalid recipient"


def test_duplicate_event_is_ignored_without_second_modification():
    handler, attempts = WebhookHandler(), [attempt()]
    webhook = event()
    handler.process_event(webhook, attempts)
    confirmed = attempts[0]
    duplicate = handler.process_event(webhook, attempts)
    assert duplicate.processing_status is WebhookProcessingStatus.DUPLICATE
    assert attempts[0] is confirmed
    assert len(handler.processed_event_ids) == 1


def test_unknown_provider_payment_is_rejected_and_not_marked_processed():
    handler, attempts = WebhookHandler(), [attempt()]
    unknown = event(provider_id="PROV-UNKNOWN")
    result = handler.process_event(unknown, attempts)
    assert result.processing_status is WebhookProcessingStatus.REJECTED
    assert result.message == "UNKNOWN_PROVIDER_PAYMENT"
    assert unknown.event_id not in handler.processed_event_ids
    assert attempts[0].status is PaymentExecutionStatus.PENDING


def test_paid_cannot_transition_to_failed():
    handler, attempts = WebhookHandler(), [attempt(PaymentExecutionStatus.PAID)]
    result = handler.process_event(event(event_type=WebhookEventType.PAYMENT_FAILED), attempts)
    assert result.processing_status is WebhookProcessingStatus.REJECTED
    assert attempts[0].status is PaymentExecutionStatus.PAID
    assert not handler.processed_event_ids


def test_failed_cannot_transition_to_paid():
    handler, attempts = WebhookHandler(), [attempt(PaymentExecutionStatus.FAILED)]
    result = handler.process_event(event(), attempts)
    assert result.processing_status is WebhookProcessingStatus.REJECTED
    assert attempts[0].status is PaymentExecutionStatus.FAILED


def test_created_cannot_transition_directly_to_paid():
    handler, attempts = WebhookHandler(), [attempt(PaymentExecutionStatus.CREATED)]
    result = handler.process_event(event(), attempts)
    assert result.processing_status is WebhookProcessingStatus.REJECTED
    assert attempts[0].status is PaymentExecutionStatus.CREATED


def test_two_event_ids_cannot_apply_two_terminal_effects():
    handler, attempts = WebhookHandler(), [attempt()]
    first = handler.process_event(event("EVT-1"), attempts)
    second = handler.process_event(
        event("EVT-2", WebhookEventType.PAYMENT_FAILED), attempts
    )
    assert first.processing_status is WebhookProcessingStatus.PROCESSED
    assert second.processing_status is WebhookProcessingStatus.REJECTED
    assert attempts[0].status is PaymentExecutionStatus.PAID
    assert handler.processed_event_ids == {"EVT-1"}
