"""Tests for approval-gated, idempotent payment initiation."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from creator_payout_ops.models import (
    ApprovalDecision,
    ApprovalRecord,
    ObligationStatus,
    PaymentExecutionStatus,
    PaymentFailureType,
    PaymentRequest,
    PayoutObligation,
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
    build_idempotency_key,
)

APPROVED_AT = datetime(2026, 1, 31, 12, 0, tzinfo=timezone.utc)


def obligation(
    *,
    status=ObligationStatus.APPROVED,
    reconciliation_status=ReconciliationStatus.READY_TO_PAY,
    expected="245.00",
    paid="0.00",
    outstanding="245.00",
    obligation_id="OBL-2026-01-C001",
):
    return PayoutObligation(
        obligation_id=obligation_id,
        creator_id="C001",
        payout_cycle_id="2026-01",
        expected_payout=Decimal(expected),
        previously_paid_amount=Decimal(paid),
        outstanding_amount=Decimal(outstanding),
        reconciliation_status=reconciliation_status,
        status=status,
    )


def approval_for(item, decision=ApprovalDecision.APPROVED, approval_id="APR-000001"):
    return ApprovalRecord(
        approval_id=approval_id,
        obligation_id=item.obligation_id,
        decision=decision,
        approved_by="finance-reviewer",
        approved_at=APPROVED_AT,
    )


def test_approved_ready_to_pay_creates_pending_payment_for_outstanding_balance():
    item = obligation()
    attempt = PaymentService(MockPaymentProvider()).initiate_payment(
        item, approval_for(item), []
    )
    assert attempt.amount == Decimal("245.00")
    assert attempt.status is PaymentExecutionStatus.PENDING
    assert attempt.provider_payment_id == "PROV-000001"
    assert attempt.internal_payment_id == "PAY-000001"
    assert attempt.internal_payment_id != attempt.provider_payment_id
    assert attempt.obligation_id == item.obligation_id
    assert attempt.approval_id == "APR-000001"


def test_approved_underpaid_obligation_pays_only_remaining_balance():
    item = obligation(
        reconciliation_status=ReconciliationStatus.UNDERPAID,
        expected="245.00",
        paid="200.00",
        outstanding="45.00",
    )
    attempt = PaymentService(MockPaymentProvider()).initiate_payment(
        item, approval_for(item), []
    )
    assert attempt.amount == Decimal("45.00")


@pytest.mark.parametrize(
    "status", [ReconciliationStatus.PAID, ReconciliationStatus.OVERPAID]
)
def test_ineligible_reconciliation_status_cannot_create_payment(status):
    item = obligation(reconciliation_status=status)
    with pytest.raises(PaymentExecutionError, match="not eligible"):
        PaymentService(MockPaymentProvider()).initiate_payment(
            item, approval_for(item), []
        )


@pytest.mark.parametrize("balance", ["0.00", "-1.00"])
def test_non_positive_balance_cannot_create_payment(balance):
    item = obligation(outstanding=balance)
    with pytest.raises(PaymentExecutionError, match="greater than zero"):
        PaymentService(MockPaymentProvider()).initiate_payment(
            item, approval_for(item), []
        )


def test_unapproved_obligation_cannot_create_payment():
    item = obligation(status=ObligationStatus.OUTSTANDING)
    with pytest.raises(PaymentExecutionError, match="not approved"):
        PaymentService(MockPaymentProvider()).initiate_payment(item, None, [])


def test_approved_obligation_without_approval_record_cannot_create_payment():
    item = obligation()
    with pytest.raises(PaymentExecutionError, match="approval record is required"):
        PaymentService(MockPaymentProvider()).initiate_payment(item, None, [])


def test_rejected_obligation_cannot_create_payment():
    item = obligation(status=ObligationStatus.REJECTED)
    rejected = approval_for(item, ApprovalDecision.REJECTED)
    with pytest.raises(PaymentExecutionError, match="Rejected"):
        PaymentService(MockPaymentProvider()).initiate_payment(item, rejected, [])


def test_approval_for_another_obligation_cannot_create_payment():
    item = obligation()
    other = ApprovalRecord(
        "APR-OTHER", "OBL-OTHER", ApprovalDecision.APPROVED,
        "finance-reviewer", APPROVED_AT,
    )
    with pytest.raises(PaymentExecutionError, match="does not match"):
        PaymentService(MockPaymentProvider()).initiate_payment(item, other, [])


@pytest.mark.parametrize(
    ("approval_id", "approved_by"), [("", "finance-reviewer"), ("APR-1", "")]
)
def test_incomplete_approval_record_cannot_create_payment(approval_id, approved_by):
    item = obligation()
    incomplete = ApprovalRecord(
        approval_id, item.obligation_id, ApprovalDecision.APPROVED,
        approved_by, APPROVED_AT,
    )
    with pytest.raises(PaymentExecutionError, match="incomplete"):
        PaymentService(MockPaymentProvider()).initiate_payment(item, incomplete, [])


def test_existing_pending_attempt_blocks_duplicate_payment():
    provider = MockPaymentProvider()
    service = PaymentService(provider)
    item = obligation()
    approval = approval_for(item)
    first = service.initiate_payment(item, approval, [])
    with pytest.raises(PaymentAlreadyPendingError, match="PAYMENT_ALREADY_PENDING"):
        service.initiate_payment(item, approval, [first])
    assert provider.created_payment_count == 1


def test_obligation_id_is_the_stable_payment_identity():
    item = obligation()
    assert build_idempotency_key(item) == "payout-OBL-2026-01-C001-USD"
    changed_amount = obligation(outstanding="200.00")
    assert build_idempotency_key(changed_amount) == build_idempotency_key(item)


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


def test_retry_same_approved_obligation_preserves_payment_identity():
    provider = MockPaymentProvider()
    provider.configure_next_behavior(ProviderBehavior.TIMEOUT_AFTER_CREATION)
    service = PaymentService(provider)
    item = obligation()
    approval = approval_for(item)
    uncertain = service.initiate_payment(item, approval, [])
    assert uncertain.status is PaymentExecutionStatus.CREATED
    assert uncertain.failure_type is PaymentFailureType.UNKNOWN
    assert uncertain.provider_payment_id is None

    recovered = service.retry_uncertain_payment(uncertain)
    assert recovered.idempotency_key == uncertain.idempotency_key
    assert recovered.obligation_id == uncertain.obligation_id
    assert recovered.approval_id == uncertain.approval_id
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
    item = obligation()
    attempt = PaymentService(provider).initiate_payment(item, approval_for(item), [])
    assert attempt.status is PaymentExecutionStatus.FAILED
    assert attempt.failure_type is failure_type
    assert attempt.failure_reason
    assert provider.created_payment_count == 0


def test_decimal_precision_is_preserved_and_quantized():
    item = obligation(expected="10.01", outstanding="10.005")
    attempt = PaymentService(MockPaymentProvider()).initiate_payment(
        item, approval_for(item), []
    )
    assert attempt.amount == Decimal("10.01")
    assert isinstance(attempt.amount, Decimal)
