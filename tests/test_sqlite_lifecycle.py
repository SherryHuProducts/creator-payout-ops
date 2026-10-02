"""Tests for durable payout lifecycle persistence and financial idempotency."""

import sqlite3
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from creator_payout_ops.models import (
    ApprovalDecision,
    CreatorPayoutSummary,
    CreatorReconciliationResult,
    ObligationStatus,
    PaymentExecutionStatus,
    ReconciliationStatus,
    WebhookEvent,
    WebhookEventType,
    WebhookProcessingStatus,
)
from creator_payout_ops.obligations import (
    create_payout_obligation,
    record_approval_decision,
)
from creator_payout_ops.payment_provider import MockPaymentProvider
from creator_payout_ops.payment_service import (
    PaymentAlreadyCompletedError,
    PaymentService,
)
from creator_payout_ops.reconciliation import reconcile_creator_payout
from creator_payout_ops.repositories import SQLiteLifecycleRepository
from creator_payout_ops.webhook_handler import PersistentWebhookHandler


def reconciliation() -> CreatorReconciliationResult:
    return CreatorReconciliationResult(
        creator_id="CR-D",
        expected_payout=Decimal("92.73"),
        amount_paid=Decimal("0.00"),
        outstanding_balance=Decimal("92.73"),
        variance=Decimal("-92.73"),
        status=ReconciliationStatus.READY_TO_PAY,
        paid_payment_count=0,
        pending_payment_count=0,
        failed_payment_count=0,
    )


def approved_lifecycle(repository: SQLiteLifecycleRepository):
    obligation = create_payout_obligation(reconciliation(), "2025-Q3")
    repository.save_obligation(obligation)
    approved, approval = record_approval_decision(
        obligation,
        approval_id="APR-000001",
        decision=ApprovalDecision.APPROVED,
        approved_by="finance-reviewer",
        approved_at=datetime(2025, 9, 30, 12, 0, tzinfo=timezone.utc),
    )
    repository.save_approval(approved, approval)
    return approved, approval


def pending_payment(repository: SQLiteLifecycleRepository):
    obligation, approval = approved_lifecycle(repository)
    provider = MockPaymentProvider()
    attempt = PaymentService(
        provider, payment_repository=repository
    ).initiate_payment(obligation, approval)
    return obligation, approval, attempt, provider


def success_event(provider_payment_id: str) -> WebhookEvent:
    return WebhookEvent(
        event_id="EVT-000001",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id=provider_payment_id,
        failure_type=None,
        failure_reason=None,
    )


def test_payout_obligation_persists_across_repository_restart(tmp_path):
    database = tmp_path / "lifecycle.sqlite3"
    repository = SQLiteLifecycleRepository(database)
    obligation = create_payout_obligation(reconciliation(), "2025-Q3")
    repository.save_obligation(obligation)
    repository.close()

    restarted = SQLiteLifecycleRepository(database)
    assert restarted.get_obligation(obligation.obligation_id) == obligation
    restarted.close()


def test_approval_and_approved_obligation_persist_across_restart(tmp_path):
    database = tmp_path / "lifecycle.sqlite3"
    repository = SQLiteLifecycleRepository(database)
    approved, approval = approved_lifecycle(repository)
    repository.close()

    restarted = SQLiteLifecycleRepository(database)
    assert restarted.get_approval(approved.obligation_id) == approval
    assert restarted.get_obligation(approved.obligation_id).status is ObligationStatus.APPROVED
    restarted.close()


def test_payment_attempt_persists_with_provider_and_business_identity(tmp_path):
    repository = SQLiteLifecycleRepository(tmp_path / "lifecycle.sqlite3")
    obligation, _approval, attempt, _provider = pending_payment(repository)

    assert repository.list_attempts(obligation.creator_id) == [attempt]
    assert attempt.idempotency_key == "payout-OBL-2025-Q3-CR-D-USD"
    repository.close()


def test_success_webhook_persists_event_and_confirmed_payment_record(tmp_path):
    repository = SQLiteLifecycleRepository(tmp_path / "lifecycle.sqlite3")
    obligation, _approval, attempt, _provider = pending_payment(repository)
    webhook = success_event(attempt.provider_payment_id)

    result = PersistentWebhookHandler(repository).process_event(
        webhook, date(2025, 9, 30)
    )

    assert result.processing_status is WebhookProcessingStatus.PROCESSED
    assert repository.has_processed(webhook.event_id)
    records = repository.list_records()
    assert len(records) == 1
    assert records[0].payment_id == attempt.internal_payment_id
    assert records[0].amount_paid == obligation.outstanding_amount
    repository.close()


def test_duplicate_webhook_after_restart_does_not_duplicate_payment(tmp_path):
    database = tmp_path / "lifecycle.sqlite3"
    repository = SQLiteLifecycleRepository(database)
    _obligation, _approval, attempt, _provider = pending_payment(repository)
    webhook = success_event(attempt.provider_payment_id)
    PersistentWebhookHandler(repository).process_event(webhook, date(2025, 9, 30))
    repository.close()

    restarted = SQLiteLifecycleRepository(database)
    duplicate = PersistentWebhookHandler(restarted).process_event(
        webhook, date(2025, 9, 30)
    )

    assert duplicate.processing_status is WebhookProcessingStatus.DUPLICATE
    assert len(restarted.list_records()) == 1
    assert restarted.list_attempts("CR-D")[0].status is PaymentExecutionStatus.PAID
    restarted.close()


def test_payment_idempotency_check_survives_restart(tmp_path):
    database = tmp_path / "lifecycle.sqlite3"
    repository = SQLiteLifecycleRepository(database)
    obligation, approval, attempt, _provider = pending_payment(repository)
    PersistentWebhookHandler(repository).process_event(
        success_event(attempt.provider_payment_id), date(2025, 9, 30)
    )
    repository.close()

    restarted = SQLiteLifecycleRepository(database)
    fresh_provider = MockPaymentProvider()
    with pytest.raises(PaymentAlreadyCompletedError, match="PAYMENT_ALREADY_COMPLETED"):
        PaymentService(
            fresh_provider, payment_repository=restarted
        ).initiate_payment(obligation, approval)
    assert fresh_provider.created_payment_count == 0
    restarted.close()


def test_final_reconciliation_uses_persisted_confirmed_payment(tmp_path):
    repository = SQLiteLifecycleRepository(tmp_path / "lifecycle.sqlite3")
    obligation, _approval, attempt, _provider = pending_payment(repository)
    PersistentWebhookHandler(repository).process_event(
        success_event(attempt.provider_payment_id), date(2025, 9, 30)
    )

    final = reconcile_creator_payout(
        CreatorPayoutSummary("CR-D", 4, Decimal("92.73")),
        repository.list_records(),
    )

    assert final.amount_paid == obligation.outstanding_amount
    assert final.outstanding_balance == Decimal("0.00")
    assert final.status is ReconciliationStatus.PAID
    repository.close()


def test_duplicate_webhook_does_not_double_count_final_paid_amount(tmp_path):
    database = tmp_path / "lifecycle.sqlite3"
    repository = SQLiteLifecycleRepository(database)
    _obligation, _approval, attempt, _provider = pending_payment(repository)
    webhook = success_event(attempt.provider_payment_id)
    handler = PersistentWebhookHandler(repository)
    handler.process_event(webhook, date(2025, 9, 30))
    repository.close()

    restarted = SQLiteLifecycleRepository(database)
    PersistentWebhookHandler(restarted).process_event(webhook, date(2025, 9, 30))
    final = reconcile_creator_payout(
        CreatorPayoutSummary("CR-D", 4, Decimal("92.73")),
        restarted.list_records(),
    )
    assert final.amount_paid == Decimal("92.73")
    assert final.paid_payment_count == 1
    restarted.close()


def test_audit_trail_reconstructs_complete_obligation_lifecycle(tmp_path):
    repository = SQLiteLifecycleRepository(tmp_path / "lifecycle.sqlite3")
    obligation, approval, attempt, _provider = pending_payment(repository)
    webhook = success_event(attempt.provider_payment_id)
    PersistentWebhookHandler(repository).process_event(webhook, date(2025, 9, 30))

    trail = repository.get_audit_trail(obligation.obligation_id)

    assert trail.obligation.status is ObligationStatus.APPROVED
    assert trail.approval == approval
    assert trail.payment_attempts[0].status is PaymentExecutionStatus.PAID
    assert trail.payment_attempts[0].provider_payment_id == attempt.provider_payment_id
    assert trail.webhook_events == (webhook,)
    assert trail.confirmed_payments[0].provider_reference == attempt.provider_payment_id
    repository.close()


def test_database_rejects_duplicate_financial_identities(tmp_path):
    repository = SQLiteLifecycleRepository(tmp_path / "lifecycle.sqlite3")
    obligation, approval, attempt, _provider = pending_payment(repository)

    with pytest.raises(sqlite3.IntegrityError):
        repository.save_obligation(obligation)
    with pytest.raises(ValueError, match="already decided"):
        repository.save_approval(obligation, approval)
    with pytest.raises(sqlite3.IntegrityError):
        repository.save_attempt(
            replace(
                attempt,
                internal_payment_id="PAY-999998",
                provider_payment_id="PROV-999998",
                attempt_number=2,
            )
        )
    with pytest.raises(sqlite3.IntegrityError):
        repository.save_attempt(
            replace(
                attempt,
                internal_payment_id="PAY-999999",
                idempotency_key="payout-another-obligation-USD",
                attempt_number=2,
            )
        )
    repository.close()
