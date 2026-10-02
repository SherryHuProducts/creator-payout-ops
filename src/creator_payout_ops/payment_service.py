"""Safe initiation of creator payments through a provider abstraction."""

from decimal import Decimal, ROUND_HALF_UP

from .models import (
    ApprovalDecision,
    ApprovalRecord,
    ObligationStatus,
    PaymentAttempt,
    PaymentExecutionStatus,
    PaymentFailureType,
    PaymentRequest,
    PayoutObligation,
)
from .obligations import PAYABLE_RECONCILIATION_STATUSES
from .payment_provider import (
    NonRetryableProviderError,
    PaymentProvider,
    ProviderTimeoutError,
    RetryableProviderError,
)
from .repositories.interfaces import PaymentRepository

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


class PaymentExecutionError(RuntimeError):
    """A payment cannot be initiated under the current domain state."""


class PaymentAlreadyPendingError(PaymentExecutionError):
    code = "PAYMENT_ALREADY_PENDING"


class PaymentAlreadyCompletedError(PaymentExecutionError):
    code = "PAYMENT_ALREADY_COMPLETED"


def build_idempotency_key(
    obligation: PayoutObligation, currency: str = "USD"
) -> str:
    """Build a stable key for one logical creator payout obligation."""

    return f"payout-{obligation.obligation_id}-{currency.upper()}"


class PaymentService:
    def __init__(
        self,
        provider: PaymentProvider,
        currency: str = "USD",
        payment_repository: PaymentRepository | None = None,
    ) -> None:
        self.provider = provider
        self.currency = currency.upper()
        self.payment_repository = payment_repository
        self._next_internal_id = (
            payment_repository.next_internal_payment_sequence()
            if payment_repository
            else 1
        )

    def _internal_id(self) -> str:
        identifier = f"PAY-{self._next_internal_id:06d}"
        self._next_internal_id += 1
        return identifier

    def _attempt(
        self,
        request: PaymentRequest,
        obligation_id: str,
        approval_id: str,
        attempt_number: int,
        status: PaymentExecutionStatus,
        provider_payment_id: str | None = None,
        failure_type: PaymentFailureType | None = None,
        failure_reason: str | None = None,
    ) -> PaymentAttempt:
        return PaymentAttempt(
            internal_payment_id=self._internal_id(),
            obligation_id=obligation_id,
            approval_id=approval_id,
            creator_id=request.creator_id,
            amount=request.amount,
            currency=request.currency,
            idempotency_key=request.idempotency_key,
            status=status,
            provider_payment_id=provider_payment_id,
            failure_type=failure_type,
            failure_reason=failure_reason,
            attempt_number=attempt_number,
        )

    def _send(
        self,
        request: PaymentRequest,
        obligation_id: str,
        approval_id: str,
        attempt_number: int,
    ) -> PaymentAttempt:
        try:
            response = self.provider.create_payment(request)
            return self._attempt(
                request, obligation_id, approval_id, attempt_number,
                response.status, response.provider_payment_id,
            )
        except ProviderTimeoutError as exc:
            # No response does not mean failure. Preserve the logical key so a
            # later retry can recover a provider payment created before timeout.
            return self._attempt(
                request, obligation_id, approval_id, attempt_number,
                PaymentExecutionStatus.CREATED,
                failure_type=PaymentFailureType.UNKNOWN, failure_reason=str(exc),
            )
        except RetryableProviderError as exc:
            return self._attempt(
                request, obligation_id, approval_id, attempt_number,
                PaymentExecutionStatus.FAILED,
                failure_type=PaymentFailureType.RETRYABLE, failure_reason=str(exc),
            )
        except NonRetryableProviderError as exc:
            return self._attempt(
                request, obligation_id, approval_id, attempt_number,
                PaymentExecutionStatus.FAILED,
                failure_type=PaymentFailureType.NON_RETRYABLE, failure_reason=str(exc),
            )

    def initiate_payment(
        self,
        obligation: PayoutObligation,
        approval: ApprovalRecord | None,
        existing_attempts: list[PaymentAttempt] | None = None,
    ) -> PaymentAttempt:
        if obligation.status is ObligationStatus.REJECTED:
            raise PaymentExecutionError("Rejected payout obligation cannot be paid")
        if obligation.status is not ObligationStatus.APPROVED:
            raise PaymentExecutionError("Payout obligation is not approved")
        if approval is None:
            raise PaymentExecutionError("Matching approval record is required")
        if not approval.approval_id.strip() or not approval.approved_by.strip():
            raise PaymentExecutionError("Approval record is incomplete")
        if approval.obligation_id != obligation.obligation_id:
            raise PaymentExecutionError("Approval record does not match payout obligation")
        if approval.decision is not ApprovalDecision.APPROVED:
            raise PaymentExecutionError("Approval decision does not authorize payment")
        if obligation.reconciliation_status not in PAYABLE_RECONCILIATION_STATUSES:
            raise PaymentExecutionError(
                f"Reconciliation status {obligation.reconciliation_status.value} "
                "is not eligible for payment"
            )
        amount = obligation.outstanding_amount.quantize(
            CENT, rounding=ROUND_HALF_UP
        )
        if amount <= ZERO:
            raise PaymentExecutionError("Outstanding balance must be greater than zero")

        persisted_attempts = (
            self.payment_repository.list_attempts(obligation.creator_id)
            if self.payment_repository
            else []
        )
        attempts_by_id = {
            attempt.internal_payment_id: attempt
            for attempt in [*persisted_attempts, *(existing_attempts or [])]
        }
        attempts = list(attempts_by_id.values())
        key = build_idempotency_key(obligation, self.currency)
        if any(
            attempt.idempotency_key == key
            and attempt.status is PaymentExecutionStatus.PENDING
            for attempt in attempts
        ):
            raise PaymentAlreadyPendingError("PAYMENT_ALREADY_PENDING")
        if any(
            attempt.idempotency_key == key
            and attempt.status is PaymentExecutionStatus.PAID
            for attempt in attempts
        ):
            raise PaymentAlreadyCompletedError("PAYMENT_ALREADY_COMPLETED")

        attempt_number = 1 + max(
            (attempt.attempt_number for attempt in attempts if attempt.idempotency_key == key),
            default=0,
        )
        attempt = self._send(
            PaymentRequest(obligation.creator_id, amount, self.currency, key),
            obligation.obligation_id,
            approval.approval_id,
            attempt_number,
        )
        if self.payment_repository:
            self.payment_repository.save_attempt(attempt)
        return attempt

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
        retried = self._send(
            request,
            attempt.obligation_id,
            attempt.approval_id,
            attempt.attempt_number + 1,
        )
        if self.payment_repository:
            self.payment_repository.save_attempt(retried)
        return retried
