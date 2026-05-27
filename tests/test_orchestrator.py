from typing import Sequence

from reverse_flight_tickets.domain import Offer, SearchRequest, Segment
from reverse_flight_tickets.providers import SkyscannerProvider
from reverse_flight_tickets.providers.base import ProviderCapability, ProviderContext
from reverse_flight_tickets.search import SearchOrchestrator
from reverse_flight_tickets.search.filters import (
    CarrierFilterResult,
    carrier_filter_warnings,
)


class StaticProvider:
    name = "static"
    capabilities = ProviderCapability()

    def __init__(self, offers: Sequence[Offer]) -> None:
        self.offers = tuple(offers)

    async def search(
        self,
        request: SearchRequest,
        context: ProviderContext | None = None,
    ) -> Sequence[Offer]:
        return self.offers


def test_orchestrator_returns_manual_provider_offer() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "allowed_markets": "US",
            "allowed_currencies": "USD",
        }
    )
    result = __import__("asyncio").run(SearchOrchestrator([SkyscannerProvider()]).search(request))

    assert len(result.offers) == 1
    assert result.offers[0].manual_check_required is True
    assert result.provider_runs[0].status == "ok"


def test_orchestrator_filters_excluded_carriers_before_ranking() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "LHR",
            "destination": "JFK",
            "departure_date": "2026-10-01",
        }
    )
    duffel_airways_offer = Offer(
        provider="duffel",
        source_market="US",
        currency="USD",
        total_amount="120.00",
        segments=(
            Segment(
                origin="LHR",
                destination="JFK",
                departure_date=request.departure_date,
                marketing_carrier="ZZ",
                flight_number="9538",
            ),
        ),
    )
    real_carrier_offer = Offer(
        provider="duffel",
        source_market="US",
        currency="USD",
        total_amount="140.00",
        segments=(
            Segment(
                origin="LHR",
                destination="JFK",
                departure_date=request.departure_date,
                marketing_carrier="BA",
                flight_number="1516",
            ),
        ),
    )

    result = __import__("asyncio").run(
        SearchOrchestrator(
            [StaticProvider((duffel_airways_offer, real_carrier_offer))],
            excluded_carriers=("zz",),
        ).search(request)
    )

    assert len(result.offers) == 1
    assert result.offers[0].segments[0].marketing_carrier == "BA"
    assert result.warnings == ("filtered 1 offer by excluded carrier: ZZ",)


def test_orchestrator_filter_warning_mentions_carrier() -> None:
    result = CarrierFilterResult(
        offers=(),
        filtered_count=1,
        excluded_carriers=("ZZ",),
    )

    assert carrier_filter_warnings(result) == ("filtered 1 offer by excluded carrier: ZZ",)
