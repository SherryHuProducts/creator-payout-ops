"""Application-level orchestration for payout calculation."""

from .. import payout_engine
from ..models import CreatorAgreement, CreatorPayoutSummary, PayoutResult, PlatformOrder


class PayoutService:
    """Coordinate payout use cases without owning payout business rules."""

    def calculate_payouts(
        self,
        orders: list[PlatformOrder],
        agreements: list[CreatorAgreement],
    ) -> list[PayoutResult]:
        """Return order-level payout decisions from the domain engine."""

        return payout_engine.calculate_payouts(orders, agreements)

    def aggregate_creator_payouts(
        self, payout_results: list[PayoutResult]
    ) -> list[CreatorPayoutSummary]:
        """Aggregate eligible payout decisions by creator."""

        return payout_engine.aggregate_creator_payouts(payout_results)
