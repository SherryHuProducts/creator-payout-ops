"""Tests for safe, idempotent payment initiation."""

from decimal import Decimal

import pytest

from creator_payout_ops.models import (
    CreatorReconciliationResult,
    PaymentExecutionStatus,
    PaymentFailureType,
    PaymentRequest,
    ReconciliationStatus,
)
from creator_payout_ops.payment_provider import (
    IdempotencyConflictError,
    MockPaymentProvider,
    ProviderBehavior,
    ProviderTimeoutError,
)
from creator_payout_ops.payment_service import (
    PaymentAlreadyPendingError,
    PaymentExecutionError,
    PaymentService,
)


def reconciliation(
    status=ReconciliationStatus.READY_TO_PAY,
    expected="245.00",
    paid="0.00",
    outstanding="245.00",
    creator_id="C001",
):
    return CreatorReconciliationResult(
        creator_id, Decimal(expected), Decimal(paid), Decimal(outstanding),
        Decimal(paid) - Decimal(expected), status, 0, 0, 0,
    )


def test_ready_to_pay_creates_pending_payment_for_outstanding_balance():
    attempt = PaymentService(MockPaymentProvider()).initiate_payment(reconciliation(), [])
    assert attempt.amount == Decimal("245.00")
    assert attempt.status is PaymentExecutionStatus.PENDING
    assert attempt.provider_payment_id == "PROV-000001"
    assert attempt.internal_payment_id == "PAY-000001"
    assert attempt.internal_payment_id != attempt.provider_payment_id


def test_underpaid_creates_payment_only_for_remaining_balance():
    result = reconciliation(ReconciliationStatus.UNDERPAID, "245.00", "200.00", "45.00")
    assert PaymentService(MockPaymentProvider()).initiate_payment(result, []).amount == Decimal("45.00")


@pytest.mark.parametrize("status", [ReconciliationStatus.PAID, ReconciliationStatus.OVERPAID])
def test_ineligible_reconciliation_status_cannot_create_payment(status):
    with pytest.raises(PaymentExecutionError, match="not eligible"):
        PaymentService(MockPaymentProvider()).initiate_payment(reconciliation(status), [])


@pytest.mark.parametrize("balance", ["0.00", "-1.00"])
def test_non_positive_balance_cannot_create_payment(balance):
    with pytest.raises(PaymentExecutionError, match="greater than zero"):
        PaymentService(MockPaymentProvider()).initiate_payment(reconciliation(outstanding=balance), [])


def test_existing_pending_attempt_blocks_duplicate_payment():
    provider = MockPaymentProvider()
    service = PaymentService(provider)
    first = service.initiate_payment(reconciliation(), [])
    with pytest.raises(PaymentAlreadyPendingError, match="PAYMENT_ALREADY_PENDING"):
        service.initiate_payment(reconciliation(), [first])
    assert provider.created_payment_count == 1


def test_provider_reuses_same_idempotency_key_without_duplicate():
    provider = MockPaymentProvider()
    request = PaymentRequest("C001", Decimal("245.00"), "USD", "stable-key")
    first = provider.create_payment(request)
    second = provider.create_payment(request)
    assert first == second
    assert provider.created_payment_count == 1


def test_provider_rejects_same_key_with_different_amount():
    provider = MockPaymentProvider()
    provider.create_payment(PaymentRequest("C001", Decimal("245.00"), "USD", "same-key"))
    with pytest.raises(IdempotencyConflictError):
        provider.create_payment(PaymentRequest("C001", Decimal("246.00"), "USD", "same-key"))


def test_timeout_after_creation_stores_provider_payment():
    provider = MockPaymentProvider()
    provider.configure_next_behavior(ProviderBehavior.TIMEOUT_AFTER_CREATION)
    request = PaymentRequest("C001", Decimal("245.00"), "USD", "timeout-key")
    with pytest.raises(ProviderTimeoutError):
        provider.create_payment(request)
    assert provider.created_payment_count == 1
    assert provider.create_payment(request).provider_payment_id == "PROV-000001"


def test_timeout_retry_reuses_key_and_recovers_original_provider_payment():
    provider = MockPaymentProvider()
    provider.configure_next_behavior(ProviderBehavior.TIMEOUT_AFTER_CREATION)
    service = PaymentService(provider)
    uncertain = service.initiate_payment(reconciliation(), [])
    assert uncertain.status is PaymentExecutionStatus.CREATED
    assert uncertain.failure_type is PaymentFailureType.UNKNOWN
    assert uncertain.provider_payment_id is None

    recovered = service.retry_uncertain_payment(uncertain)
    assert recovered.idempotency_key == uncertain.idempotency_key
    assert recovered.status is PaymentExecutionStatus.PENDING
    assert recovered.provider_payment_id == "PROV-000001"
    assert recovered.attempt_number == 2
    assert provider.created_payment_count == 1


@pytest.mark.parametrize(
    ("behavior", "failure_type"),
    [
        (ProviderBehavior.RETRYABLE_ERROR, PaymentFailureType.RETRYABLE),
        (ProviderBehavior.NON_RETRYABLE_ERROR, PaymentFailureType.NON_RETRYABLE),
    ],
)
def test_provider_failures_are_recorded(behavior, failure_type):
    provider = MockPaymentProvider()
    provider.configure_next_behavior(behavior)
    attempt = PaymentService(provider).initiate_payment(reconciliation(), [])
    assert attempt.status is PaymentExecutionStatus.FAILED
    assert attempt.failure_type is failure_type
    assert attempt.failure_reason
    assert provider.created_payment_count == 0


def test_decimal_precision_is_preserved_and_quantized():
    attempt = PaymentService(MockPaymentProvider()).initiate_payment(
        reconciliation(expected="10.01", outstanding="10.005"), []
    )
    assert attempt.amount == Decimal("10.01")
    assert isinstance(attempt.amount, Decimal)
