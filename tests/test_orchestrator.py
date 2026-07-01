from decimal import Decimal
from typing import Sequence

from reverse_flight_tickets.domain import (
    Layover,
    Offer,
    RiskFlag,
    SearchRequest,
    Segment,
    TicketingType,
)
from reverse_flight_tickets.pricing import StaticRateConverter
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


class MultiCityProvider(StaticProvider):
    capabilities = ProviderCapability(supports_multi_city=True)


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


def test_orchestrator_filters_offers_over_max_layover_hours() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "LHR",
            "destination": "JFK",
            "departure_date": "2026-10-01",
            "max_layover_hours": 4,
        }
    )
    short_layover_offer = Offer(
        provider="mock",
        source_market="US",
        currency="USD",
        total_amount="300.00",
        segments=request.segments,
        layovers=(Layover(airport="KEF", duration_minutes=120),),
    )
    long_layover_offer = Offer(
        provider="mock",
        source_market="US",
        currency="USD",
        total_amount="200.00",
        segments=request.segments,
        layovers=(Layover(airport="KEF", duration_minutes=360),),
    )

    result = __import__("asyncio").run(
        SearchOrchestrator([StaticProvider((short_layover_offer, long_layover_offer))]).search(
            request
        )
    )

    assert len(result.offers) == 1
    assert result.offers[0].total_amount == Decimal("300.00")
    assert result.offers[0].layovers[0].duration_minutes == 120
    assert RiskFlag.HIDDEN_CITY_EXCLUDED in result.offers[0].risk_flags
    assert result.warnings == ("filtered 1 offer by max layover: 4h",)


def test_orchestrator_expands_date_flexibility_and_labels_policy() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "date_flexibility_days": 1,
            "allowed_markets": "US",
            "allowed_currencies": "USD",
        }
    )
    offer = Offer(
        provider="mock",
        source_market="US",
        currency="USD",
        total_amount="100.00",
        ticketing_type=TicketingType.SPLIT_TICKET,
    )

    result = __import__("asyncio").run(SearchOrchestrator([StaticProvider((offer,))]).search(request))

    assert len(result.provider_runs) == 3
    assert {run.variant.date_shift_days for run in result.provider_runs} == {-1, 0, 1}
    assert RiskFlag.SPLIT_TICKET in result.offers[0].risk_flags
    assert RiskFlag.HIDDEN_CITY_EXCLUDED in result.offers[0].risk_flags


def test_orchestrator_generates_stopover_multi_city_variants() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "stopovers": "HND",
        }
    )
    offer = Offer(
        provider="mock",
        source_market="US",
        currency="USD",
        total_amount="100.00",
    )

    result = __import__("asyncio").run(SearchOrchestrator([MultiCityProvider((offer,))]).search(request))

    assert len(result.provider_runs) == 2
    assert {run.variant.stopover for run in result.provider_runs} == {None, "HND"}
    stopover_run = next(run for run in result.provider_runs if run.variant.stopover == "HND")
    assert [segment.origin for segment in stopover_run.variant.request.segments] == ["PVG", "HND"]
    assert [segment.destination for segment in stopover_run.variant.request.segments] == ["HND", "LAX"]


def test_orchestrator_skips_multi_city_when_provider_lacks_capability() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "stopovers": "HND",
        }
    )

    result = __import__("asyncio").run(SearchOrchestrator([StaticProvider(())]).search(request))

    skipped = [run for run in result.provider_runs if run.status == "skipped"]
    assert len(skipped) == 1
    assert skipped[0].variant.stopover == "HND"
    assert skipped[0].to_dict()["variant"]["stopover"] == "HND"


def test_orchestrator_applies_comparable_pricing_before_ranking() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "allowed_currencies": "CNY",
        }
    )
    offer = Offer(
        provider="mock",
        source_market="US",
        currency="USD",
        total_amount="100.00",
    )

    result = __import__("asyncio").run(
        SearchOrchestrator(
            [StaticProvider((offer,))],
            exchange_rates={("USD", "CNY"): Decimal("7.20")},
            payment_fee_rate=Decimal("0.02"),
        ).search(request)
    )

    assert result.offers[0].currency == "CNY"
    assert result.offers[0].comparable_amount == Decimal("734.40")


def test_orchestrator_accepts_injected_currency_converter() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "allowed_currencies": "CNY",
        }
    )
    offer = Offer(
        provider="mock",
        source_market="US",
        currency="USD",
        total_amount="100.00",
    )

    result = __import__("asyncio").run(
        SearchOrchestrator(
            [StaticProvider((offer,))],
            currency_converter=StaticRateConverter(rates={("USD", "CNY"): Decimal("7.10")}),
        ).search(request)
    )

    assert result.offers[0].currency == "CNY"
    assert result.offers[0].comparable_amount == Decimal("710.00")
