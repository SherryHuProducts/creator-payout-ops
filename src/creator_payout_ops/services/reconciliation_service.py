"""Application-level orchestration for payout reconciliation."""

from .. import reconciliation
from ..models import CreatorPayoutSummary, CreatorReconciliationResult, PaymentRecord


class ReconciliationService:
    """Coordinate reconciliation without owning reconciliation rules."""

    def reconcile_payouts(
        self,
        payout_summaries: list[CreatorPayoutSummary],
        payment_records: list[PaymentRecord],
    ) -> list[CreatorReconciliationResult]:
        """Reconcile creator summaries against historical payments."""

        return reconciliation.reconcile_payouts(payout_summaries, payment_records)
