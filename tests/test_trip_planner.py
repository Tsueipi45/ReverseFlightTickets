from decimal import Decimal
from typing import Sequence

from reverse_flight_tickets.domain import Layover, Offer, SearchRequest, Segment
from reverse_flight_tickets.providers import ProviderContext
from reverse_flight_tickets.providers.base import ProviderCapability
from reverse_flight_tickets.trip_planner import (
    TripPlanRequest,
    TripPlanner,
    city_options,
    rail_connection_options,
)


class RoutePriceProvider:
    name = "route_price"
    capabilities = ProviderCapability()

    def __init__(
        self,
        prices: dict[tuple[str, str], str | tuple[str, str] | None],
    ) -> None:
        self.prices = prices

    async def search(
        self,
        request: SearchRequest,
        context: ProviderContext | None = None,
    ) -> Sequence[Offer]:
        price = self.prices.get((request.origin, request.destination))
        if price is None:
            return (
                Offer(
                    provider=self.name,
                    source_market=request.allowed_markets[0],
                    currency=request.allowed_currencies[0],
                    total_amount=None,
                    segments=request.segments,
                    booking_link=f"https://example.test/{request.origin}-{request.destination}",
                    manual_check_required=True,
                ),
            )
        amount, currency = (
            price if isinstance(price, tuple) else (price, request.allowed_currencies[0])
        )
        return (
            Offer(
                provider=self.name,
                source_market=request.allowed_markets[0],
                currency=currency,
                total_amount=amount,
                segments=(
                    Segment(
                        origin=request.origin,
                        destination=request.destination,
                        departure_date=request.departure_date,
                        marketing_carrier="MU",
                        flight_number="5001",
                    ),
                ),
                travel_duration_minutes=120,
                booking_link=f"https://example.test/{request.origin}-{request.destination}",
            ),
        )


class MixedConnectionProvider:
    name = "mixed_connection"
    capabilities = ProviderCapability(supports_multi_city=True)

    async def search(
        self,
        request: SearchRequest,
        context: ProviderContext | None = None,
    ) -> Sequence[Offer]:
        direct = Offer(
            provider=self.name,
            source_market=request.allowed_markets[0],
            currency=request.allowed_currencies[0],
            total_amount="2000",
            segments=(
                Segment(
                    origin=request.origin,
                    destination=request.destination,
                    departure_date=request.departure_date,
                    marketing_carrier="MU",
                    flight_number="5001",
                ),
            ),
            booking_link="https://example.test/direct",
        )
        via_hkg = Offer(
            provider=self.name,
            source_market=request.allowed_markets[0],
            currency=request.allowed_currencies[0],
            total_amount="1500",
            segments=(
                Segment(
                    origin=request.origin,
                    destination="HKG",
                    departure_date=request.departure_date,
                    marketing_carrier="HX",
                    flight_number="101",
                ),
                Segment(
                    origin="HKG",
                    destination=request.destination,
                    departure_date=request.departure_date,
                    marketing_carrier="HX",
                    flight_number="102",
                ),
            ),
            layovers=(Layover(airport="HKG", duration_minutes=120),),
            booking_link="https://example.test/via-hkg",
        )
        return (direct, via_hkg)


def test_trip_planner_compares_nanjing_flight_with_shanghai_rail_flight() -> None:
    request = TripPlanRequest.from_mapping(
        {
            "departure_date": "2026-07-01",
            "return_date": "2026-07-08",
            "target_currency": "CNY",
        }
    )
    planner = TripPlanner(
        [
            RoutePriceProvider(
                {
                    ("NKG", "TPE"): "2200",
                    ("NKG", "TSA"): "2300",
                    ("PVG", "TPE"): "1200",
                    ("PVG", "TSA"): "1400",
                    ("SHA", "TPE"): "1600",
                    ("SHA", "TSA"): "1500",
                }
            )
        ]
    )

    result = __import__("asyncio").run(planner.plan(request))

    assert result.recommended_option is not None
    assert result.recommended_option.option_id == "shanghai-rail-flight"
    assert result.recommended_option.flight_amount == Decimal("1200.00")
    assert result.recommended_option.ground_amount == Decimal("360.00")
    assert result.recommended_option.total_amount == Decimal("1560.00")
    assert "Nanjing rail to Shanghai plus Shanghai flight to Taipei" in result.summary
    assert "640.00 CNY" in result.summary


def test_trip_planner_marks_manual_links_as_needing_flight_price() -> None:
    request = TripPlanRequest.from_mapping(
        {
            "departure_date": "2026-07-01",
            "return_date": "2026-07-08",
        }
    )
    planner = TripPlanner([RoutePriceProvider({})])

    result = __import__("asyncio").run(planner.plan(request))

    assert {option.price_status for option in result.options} == {"needs_manual_flight_price"}
    assert all(option.total_amount is None for option in result.options)
    assert result.summary.startswith("Need priced flight offers")
    assert result.warnings == (
        "some plans need imported or API-priced flight offers",
        "rail costs are static MVP estimates, not live rail inventory",
    )


def test_trip_planner_surfaces_foreign_currency_when_rate_is_missing() -> None:
    request = TripPlanRequest.from_mapping(
        {
            "departure_date": "2026-07-01",
            "return_date": "2026-07-08",
            "target_currency": "CNY",
        }
    )
    planner = TripPlanner([RoutePriceProvider({("NKG", "TPE"): ("327.70", "USD")})])

    result = __import__("asyncio").run(planner.plan(request))
    direct = next(option for option in result.options if option.option_id == "nanjing-flight")

    assert direct.flight_amount == Decimal("327.70")
    assert direct.flight_currency == "USD"
    assert direct.total_amount is None
    assert direct.price_status == "needs_exchange_rate"


def test_trip_planner_applies_manual_exchange_rate() -> None:
    request = TripPlanRequest.from_mapping(
        {
            "departure_date": "2026-07-01",
            "return_date": "2026-07-08",
            "target_currency": "CNY",
            "manual_exchange_rates": ("USD:CNY=7.20",),
            "include_shanghai_rail": False,
        }
    )
    planner = TripPlanner([RoutePriceProvider({("NKG", "TPE"): ("327.70", "USD")})])

    result = __import__("asyncio").run(planner.plan(request))
    direct = result.options[0]

    assert direct.flight_amount == Decimal("2359.44")
    assert direct.flight_currency == "CNY"
    assert direct.total_amount == Decimal("2359.44")
    assert direct.price_status == "priced"


def test_trip_planner_supports_more_city_airport_pairs() -> None:
    request = TripPlanRequest.from_mapping(
        {
            "origin_city": "Beijing",
            "destination_city": "Taipei",
            "departure_date": "2026-07-01",
            "return_date": "2026-07-08",
            "include_shanghai_rail": False,
        }
    )
    planner = TripPlanner([RoutePriceProvider({("PEK", "TPE"): "2600", ("PKX", "TSA"): "2400"})])

    result = __import__("asyncio").run(planner.plan(request))

    assert result.recommended_option is not None
    assert result.recommended_option.option_id == "beijing-flight"
    assert result.recommended_option.flight_origin_airports == ("PEK", "PKX")
    assert result.recommended_option.flight_destination_airports == ("TPE", "TSA")
    assert result.recommended_option.flight_amount == Decimal("2400.00")


def test_trip_planner_builds_selected_rail_connection_city() -> None:
    request = TripPlanRequest.from_mapping(
        {
            "origin_city": "Hangzhou",
            "destination_city": "Taipei",
            "departure_date": "2026-07-01",
            "return_date": "2026-07-08",
            "include_shanghai_rail": False,
            "rail_connection_city": "Shanghai",
        }
    )
    planner = TripPlanner([RoutePriceProvider({("HGH", "TPE"): "1600", ("PVG", "TPE"): "1000"})])

    result = __import__("asyncio").run(planner.plan(request))
    rail = next(option for option in result.options if option.option_id == "shanghai-rail-flight")

    assert rail.ground_amount == Decimal("200.00")
    assert rail.total_amount == Decimal("1200.00")
    assert rail.ground_legs[0].origin == "Hangzhou East"


def test_trip_planner_builds_airport_stopover_option() -> None:
    request = TripPlanRequest.from_mapping(
        {
            "origin_city": "Nanjing",
            "destination_city": "Taipei",
            "departure_date": "2026-07-01",
            "return_date": "2026-07-08",
            "include_shanghai_rail": False,
            "airport_stopover_city": "Hong Kong",
        }
    )
    planner = TripPlanner([RoutePriceProvider({("NKG", "TPE"): "2200", ("NKG", "TSA"): "2300"})])

    result = __import__("asyncio").run(planner.plan(request))
    stopover = next(option for option in result.options if option.kind == "airport_stopover")

    assert stopover.option_id == "hongkong-airport-stopover"
    assert stopover.flight_origin_airports == ("NKG",)
    assert stopover.flight_destination_airports == ("TPE", "TSA")
    assert len(stopover.searches[0].request.segments) == 4
    assert stopover.searches[0].request.segments[0].destination == "HKG"


def test_trip_planner_filters_to_direct_flights_only() -> None:
    request = TripPlanRequest.from_mapping(
        {
            "origin_city": "Nanjing",
            "destination_city": "Taipei",
            "departure_date": "2026-07-01",
            "return_date": "2026-07-08",
            "include_shanghai_rail": False,
            "flight_filter": "direct",
        }
    )
    planner = TripPlanner([MixedConnectionProvider()])

    result = __import__("asyncio").run(planner.plan(request))
    direct = result.options[0]

    assert direct.flight_amount == Decimal("2000.00")
    assert direct.flight_offers
    assert {offer.booking_link for offer in direct.flight_offers} == {"https://example.test/direct"}
    assert all(not offer.layovers for offer in direct.flight_offers)


def test_trip_planner_filters_to_selected_stopover_city() -> None:
    request = TripPlanRequest.from_mapping(
        {
            "origin_city": "Nanjing",
            "destination_city": "Taipei",
            "departure_date": "2026-07-01",
            "return_date": "2026-07-08",
            "include_shanghai_rail": False,
            "flight_filter": "via_city",
            "flight_stopover_city": "Hong Kong",
        }
    )
    planner = TripPlanner([MixedConnectionProvider()])

    result = __import__("asyncio").run(planner.plan(request))
    via = result.options[0]

    assert via.flight_amount == Decimal("1500.00")
    assert via.flight_offers
    assert {offer.booking_link for offer in via.flight_offers} == {"https://example.test/via-hkg"}
    assert all(offer.layovers[0].airport == "HKG" for offer in via.flight_offers)
    assert via.searches[0].request.stopovers == ("HKG",)


def test_trip_planner_requires_stopover_city_for_via_city_filter() -> None:
    try:
        TripPlanRequest.from_mapping(
            {
                "origin_city": "Nanjing",
                "destination_city": "Taipei",
                "departure_date": "2026-07-01",
                "return_date": "2026-07-08",
                "flight_filter": "via_city",
            }
        )
    except ValueError as exc:
        assert "flight_stopover_city is required" in str(exc)
    else:
        raise AssertionError("expected via_city without city to fail")


def test_trip_planner_rejects_unknown_city() -> None:
    try:
        TripPlanRequest.from_mapping(
            {
                "origin_city": "NewYork",
                "destination_city": "Taipei",
                "departure_date": "2026-07-01",
                "return_date": "2026-07-08",
            }
        )
    except ValueError as exc:
        assert "unsupported city" in str(exc)
    else:
        raise AssertionError("expected unsupported city to fail")


def test_trip_planner_exposes_city_and_rail_metadata() -> None:
    city_values = {option["value"] for option in city_options()}

    assert {"Nanjing", "Shanghai", "Beijing", "Hong Kong", "Macau"} <= city_values
    assert rail_connection_options("Nanjing", "Taipei")[0]["value"] == "Shanghai"
