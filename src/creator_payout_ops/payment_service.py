"""Safe initiation of creator payments through a provider abstraction."""

from decimal import Decimal, ROUND_HALF_UP

from .models import (
    CreatorReconciliationResult,
    PaymentAttempt,
    PaymentExecutionStatus,
    PaymentFailureType,
    PaymentRequest,
    ReconciliationStatus,
)
from .payment_provider import (
    NonRetryableProviderError,
    PaymentProvider,
    ProviderTimeoutError,
    RetryableProviderError,
)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


class PaymentExecutionError(RuntimeError):
    """A payment cannot be initiated under the current domain state."""


class PaymentAlreadyPendingError(PaymentExecutionError):
    code = "PAYMENT_ALREADY_PENDING"


def build_idempotency_key(
    reconciliation_result: CreatorReconciliationResult, currency: str = "USD"
) -> str:
    """Build a stable key for one logical creator payout obligation."""

    expected = reconciliation_result.expected_payout.quantize(CENT, rounding=ROUND_HALF_UP)
    outstanding = reconciliation_result.outstanding_balance.quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    return (
        f"creator-{reconciliation_result.creator_id}"
        f"-expected-{expected}-outstanding-{outstanding}-{currency.upper()}"
    )


class PaymentService:
    def __init__(self, provider: PaymentProvider, currency: str = "USD") -> None:
        self.provider = provider
        self.currency = currency.upper()
        self._next_internal_id = 1

    def _internal_id(self) -> str:
        identifier = f"PAY-{self._next_internal_id:06d}"
        self._next_internal_id += 1
        return identifier

    def _attempt(
        self,
        request: PaymentRequest,
        attempt_number: int,
        status: PaymentExecutionStatus,
        provider_payment_id: str | None = None,
        failure_type: PaymentFailureType | None = None,
        failure_reason: str | None = None,
    ) -> PaymentAttempt:
        return PaymentAttempt(
            self._internal_id(), request.creator_id, request.amount, request.currency,
            request.idempotency_key, status, provider_payment_id, failure_type,
            failure_reason, attempt_number,
        )

    def _send(self, request: PaymentRequest, attempt_number: int) -> PaymentAttempt:
        try:
            response = self.provider.create_payment(request)
            return self._attempt(
                request, attempt_number, response.status, response.provider_payment_id
            )
        except ProviderTimeoutError as exc:
            # No response does not mean failure. Preserve the logical key so a
            # later retry can recover a provider payment created before timeout.
            return self._attempt(
                request, attempt_number, PaymentExecutionStatus.CREATED,
                failure_type=PaymentFailureType.UNKNOWN, failure_reason=str(exc),
            )
        except RetryableProviderError as exc:
            return self._attempt(
                request, attempt_number, PaymentExecutionStatus.FAILED,
                failure_type=PaymentFailureType.RETRYABLE, failure_reason=str(exc),
            )
        except NonRetryableProviderError as exc:
            return self._attempt(
                request, attempt_number, PaymentExecutionStatus.FAILED,
                failure_type=PaymentFailureType.NON_RETRYABLE, failure_reason=str(exc),
            )

    def initiate_payment(
        self,
        reconciliation_result: CreatorReconciliationResult,
        existing_attempts: list[PaymentAttempt],
    ) -> PaymentAttempt:
        eligible = {
            ReconciliationStatus.READY_TO_PAY,
            ReconciliationStatus.UNDERPAID,
        }
        if reconciliation_result.status not in eligible:
            raise PaymentExecutionError(
                f"Reconciliation status {reconciliation_result.status.value} is not eligible for payment"
            )
        amount = reconciliation_result.outstanding_balance.quantize(
            CENT, rounding=ROUND_HALF_UP
        )
        if amount <= ZERO:
            raise PaymentExecutionError("Outstanding balance must be greater than zero")

        key = build_idempotency_key(reconciliation_result, self.currency)
        if any(
            attempt.idempotency_key == key
            and attempt.status is PaymentExecutionStatus.PENDING
            for attempt in existing_attempts
        ):
            raise PaymentAlreadyPendingError("PAYMENT_ALREADY_PENDING")

        attempt_number = 1 + max(
            (attempt.attempt_number for attempt in existing_attempts if attempt.idempotency_key == key),
            default=0,
        )
        return self._send(
            PaymentRequest(reconciliation_result.creator_id, amount, self.currency, key),
            attempt_number,
        )

    def retry_uncertain_payment(self, attempt: PaymentAttempt) -> PaymentAttempt:
        """Retry an uncertain request without changing its logical identity."""

        if not (
            attempt.status is PaymentExecutionStatus.CREATED
            and attempt.failure_type is PaymentFailureType.UNKNOWN
        ):
            raise PaymentExecutionError("Only an uncertain payment attempt may be retried")
        request = PaymentRequest(
            attempt.creator_id, attempt.amount, attempt.currency, attempt.idempotency_key
        )
        return self._send(request, attempt.attempt_number + 1)
