"""Application orchestration behind the thin FastAPI adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..loaders import (
    load_creator_agreements,
    load_payment_records,
    load_platform_orders,
)
from ..models import (
    ApprovalDecision,
    ApprovalRecord,
    CreatorPayoutSummary,
    CreatorReconciliationResult,
    PaymentAttempt,
    PaymentRecord,
    PaymentStatus,
    PayoutAuditTrail,
    PayoutObligation,
    WebhookEvent,
    WebhookProcessingResult,
)
from ..obligations import (
    build_obligation_id,
    create_payout_obligation,
    record_approval_decision,
)
from ..payment_provider import MockPaymentProvider
from ..payment_service import PaymentService
from ..reconciliation import reconcile_creator_payout
from ..repositories import SQLiteLifecycleRepository
from ..services.payout_service import PayoutService
from ..services.reconciliation_service import ReconciliationService
from ..webhook_handler import PersistentWebhookHandler


class ResourceNotFound(LookupError):
    """The requested lifecycle resource does not exist."""


class LifecycleConflict(RuntimeError):
    """The requested operation conflicts with persisted lifecycle state."""


@dataclass(frozen=True)
class LifecycleProjection:
    audit_trail: PayoutAuditTrail
    reconciliation: CreatorReconciliationResult


class PayoutLifecycleApplication:
    """Coordinate existing domain services and SQLite persistence."""

    def __init__(
        self,
        repository: SQLiteLifecycleRepository,
        demo_data_directory: Path,
        provider: MockPaymentProvider | None = None,
    ) -> None:
        self.repository = repository
        self.demo_data_directory = demo_data_directory
        self.provider = provider or MockPaymentProvider()
        self.payout_service = PayoutService()
        self.reconciliation_service = ReconciliationService()

    def close(self) -> None:
        self.repository.close()

    def reconcile_cycle(
        self, payout_cycle_id: str, creator_id: str
    ) -> PayoutObligation:
        obligation_id = build_obligation_id(creator_id, payout_cycle_id)
        if self.repository.get_obligation(obligation_id):
            raise LifecycleConflict(
                f"Payout obligation {obligation_id} already exists"
            )

        orders = load_platform_orders(self.demo_data_directory / "platform_orders.csv")
        agreements = load_creator_agreements(
            self.demo_data_directory / "creator_agreements.csv"
        )
        historical_payments = load_payment_records(
            self.demo_data_directory / "payment_records.csv"
        )
        payout_results = self.payout_service.calculate_payouts(orders, agreements)
        summaries = self.payout_service.aggregate_creator_payouts(payout_results)
        summary = next(
            (item for item in summaries if item.creator_id == creator_id), None
        )
        if summary is None:
            raise ResourceNotFound(f"Creator {creator_id} was not found")

        reconciled = self.reconciliation_service.reconcile_payouts(
            [summary], historical_payments
        )[0]
        obligation = create_payout_obligation(reconciled, payout_cycle_id)
        self.repository.save_obligation(obligation)
        return obligation

    def approve(
        self, obligation_id: str, approval_id: str, approved_by: str
    ) -> tuple[PayoutObligation, ApprovalRecord]:
        obligation = self._obligation(obligation_id)
        approved, approval = record_approval_decision(
            obligation,
            approval_id=approval_id,
            decision=ApprovalDecision.APPROVED,
            approved_by=approved_by,
            approved_at=datetime.now(timezone.utc),
        )
        self.repository.save_approval(approved, approval)
        return approved, approval

    def initiate_payment(self, obligation_id: str) -> PaymentAttempt:
        obligation = self._obligation(obligation_id)
        approval = self.repository.get_approval(obligation_id)
        return PaymentService(
            self.provider, payment_repository=self.repository
        ).initiate_payment(obligation, approval)

    def process_webhook(
        self, event: WebhookEvent, payment_date: date
    ) -> WebhookProcessingResult:
        return PersistentWebhookHandler(self.repository).process_event(
            event, payment_date
        )

    def lifecycle(self, obligation_id: str) -> LifecycleProjection:
        try:
            trail = self.repository.get_audit_trail(obligation_id)
        except KeyError as exc:
            raise ResourceNotFound(str(exc)) from exc

        baseline: list[PaymentRecord] = []
        if trail.obligation.previously_paid_amount > Decimal("0.00"):
            baseline.append(
                PaymentRecord(
                    payment_id=f"BASELINE-{trail.obligation.obligation_id}",
                    creator_id=trail.obligation.creator_id,
                    payment_date=date.min,
                    amount_paid=trail.obligation.previously_paid_amount,
                    payment_status=PaymentStatus.PAID,
                    provider_reference=None,
                )
            )
        summary = CreatorPayoutSummary(
            creator_id=trail.obligation.creator_id,
            eligible_order_count=0,
            expected_payout=trail.obligation.expected_payout,
        )
        final = reconcile_creator_payout(
            summary, [*baseline, *trail.confirmed_payments]
        )
        return LifecycleProjection(trail, final)

    def _obligation(self, obligation_id: str) -> PayoutObligation:
        obligation = self.repository.get_obligation(obligation_id)
        if obligation is None:
            raise ResourceNotFound(f"Payout obligation {obligation_id} was not found")
        return obligation
