"""Provider abstraction and deterministic in-memory payment provider."""

from enum import Enum
from typing import Protocol

from .models import PaymentExecutionStatus, PaymentRequest, ProviderPaymentResponse


class ProviderBehavior(str, Enum):
    NORMAL = "NORMAL"
    TIMEOUT_AFTER_CREATION = "TIMEOUT_AFTER_CREATION"
    RETRYABLE_ERROR = "RETRYABLE_ERROR"
    NON_RETRYABLE_ERROR = "NON_RETRYABLE_ERROR"


class PaymentProviderError(RuntimeError):
    """Base error returned by a payment provider adapter."""


class ProviderTimeoutError(PaymentProviderError):
    """The provider request outcome is uncertain."""


class RetryableProviderError(PaymentProviderError):
    """A confirmed provider error that may be retried later."""


class NonRetryableProviderError(PaymentProviderError):
    """A confirmed provider error requiring correction or review."""


class IdempotencyConflictError(PaymentProviderError):
    """An idempotency key was reused for different request parameters."""


class PaymentProvider(Protocol):
    def create_payment(self, request: PaymentRequest) -> ProviderPaymentResponse:
        """Create or retrieve one idempotent provider payment."""


class MockPaymentProvider:
    """A controllable external provider simulation with in-memory storage."""

    def __init__(self) -> None:
        self._payments: dict[str, tuple[PaymentRequest, ProviderPaymentResponse]] = {}
        self._next_behavior = ProviderBehavior.NORMAL
        self._next_provider_id = 1

    @property
    def created_payment_count(self) -> int:
        return len(self._payments)

    def configure_next_behavior(self, behavior: ProviderBehavior) -> None:
        self._next_behavior = behavior

    def create_payment(self, request: PaymentRequest) -> ProviderPaymentResponse:
        existing = self._payments.get(request.idempotency_key)
        if existing:
            original_request, response = existing
            if (
                original_request.creator_id != request.creator_id
                or original_request.amount != request.amount
                or original_request.currency != request.currency
            ):
                raise IdempotencyConflictError(
                    "Idempotency key was already used with different payment parameters"
                )
            return response

        behavior = self._next_behavior
        self._next_behavior = ProviderBehavior.NORMAL
        if behavior is ProviderBehavior.RETRYABLE_ERROR:
            raise RetryableProviderError("Simulated retryable provider error")
        if behavior is ProviderBehavior.NON_RETRYABLE_ERROR:
            raise NonRetryableProviderError("Simulated non-retryable provider error")

        provider_id = f"PROV-{self._next_provider_id:06d}"
        self._next_provider_id += 1
        response = ProviderPaymentResponse(
            provider_payment_id=provider_id,
            status=PaymentExecutionStatus.PENDING,
            idempotency_key=request.idempotency_key,
        )
        self._payments[request.idempotency_key] = (request, response)
        if behavior is ProviderBehavior.TIMEOUT_AFTER_CREATION:
            raise ProviderTimeoutError("Provider created payment before network timeout")
        return response
