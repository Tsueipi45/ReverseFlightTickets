from decimal import Decimal

from reverse_flight_tickets.domain import Offer, RiskFlag
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
