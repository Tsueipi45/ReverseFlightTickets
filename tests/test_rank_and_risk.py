from decimal import Decimal

from reverse_flight_tickets.domain import ChangeRefundRule, Offer, RiskFlag, SearchRequest
from reverse_flight_tickets.providers.base import ProviderCapability, ProviderContext
from reverse_flight_tickets.search import SearchOrchestrator
from reverse_flight_tickets.search.rank import rank_offers
from reverse_flight_tickets.search.reverse_strategy import risk_score


def test_rank_prefers_priced_offer_before_manual_offer() -> None:
    manual = Offer(
        provider="manual",
        source_market="US",
        currency="USD",
        risk_flags=(RiskFlag.MANUAL_CHECK_REQUIRED,),
    )
    priced = Offer(
        provider="api",
        source_market="US",
        currency="USD",
        total_amount=Decimal("500"),
    )

    assert rank_offers((manual, priced))[0].provider == "api"


def test_risk_score_weights_split_ticket() -> None:
    offer = Offer(
        provider="mock",
        source_market="US",
        currency="USD",
        risk_flags=(RiskFlag.SPLIT_TICKET, RiskFlag.PROVIDER_UNVERIFIED),
    )

    assert risk_score(offer) == 30


def test_risk_score_weights_refund_and_change_rules() -> None:
    offer = Offer(
        provider="mock",
        source_market="US",
        currency="USD",
        fare_rules=(
            ChangeRefundRule(
                refund_allowed=False,
                change_allowed=False,
                penalty_amount=Decimal("100"),
                currency="USD",
            ),
        ),
    )

    assert risk_score(offer) == 35


def test_recommendations_include_savings_vs_risk_ordering() -> None:
    class StaticProvider:
        name = "static"
        capabilities = ProviderCapability()

        async def search(
            self,
            request: SearchRequest,
            context: ProviderContext | None = None,
        ) -> tuple[Offer, ...]:
            return (
                Offer(
                    provider="low",
                    source_market="US",
                    currency="USD",
                    total_amount=Decimal("100"),
                    risk_flags=(RiskFlag.SPLIT_TICKET,),
                ),
                Offer(
                    provider="high",
                    source_market="US",
                    currency="USD",
                    total_amount=Decimal("150"),
                ),
            )

    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
        }
    )

    result = __import__("asyncio").run(SearchOrchestrator([StaticProvider()]).search(request))

    savings = result.recommendations.savings_vs_risk
    assert savings[0].offer.provider == "low"
    assert savings[0].savings_amount == Decimal("50")
    assert savings[0].risk_score == 25
