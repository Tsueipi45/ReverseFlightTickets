import asyncio

import httpx
import respx

from reverse_flight_tickets.domain import RiskFlag, SearchRequest, TicketingType
from reverse_flight_tickets.providers import DuffelProvider, ProviderContext, ProviderNotConfigured
from reverse_flight_tickets.providers.duffel import DUFFEL_API_BASE_URL
from reverse_flight_tickets.providers.base import ProviderError


def _request() -> SearchRequest:
    return SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "passenger_count": 1,
            "cabin": "business",
            "allowed_markets": "US",
            "allowed_currencies": "USD",
        }
    )


def _duffel_offer_response() -> dict[str, object]:
    return {
        "data": {
            "id": "orq_123",
            "offers": [
                {
                    "id": "off_123",
                    "live_mode": False,
                    "total_amount": "1234.56",
                    "total_currency": "USD",
                    "base_amount": "1000.00",
                    "tax_amount": "234.56",
                    "expires_at": "2026-05-28T00:00:00Z",
                    "conditions": {
                        "change_before_departure": {"allowed": True},
                        "refund_before_departure": {"allowed": False},
                    },
                    "owner": {"name": "Duffel Airways"},
                    "slices": [
                        {
                            "duration": "P1DT10H15M",
                            "segments": [
                                {
                                    "origin": {"iata_code": "PVG"},
                                    "destination": {"iata_code": "HND"},
                                    "departing_at": "2026-10-01T12:30:00",
                                    "arriving_at": "2026-10-01T16:00:00",
                                    "marketing_carrier": {"iata_code": "ZZ"},
                                    "marketing_carrier_flight_number": "100",
                                    "passengers": [
                                        {
                                            "baggages": [
                                                {"type": "checked", "quantity": 1},
                                                {"type": "carry_on", "quantity": 1},
                                            ]
                                        }
                                    ],
                                }
                                ,
                                {
                                    "origin": {"iata_code": "HND"},
                                    "destination": {"iata_code": "LAX"},
                                    "departing_at": "2026-10-01T18:30:00",
                                    "arriving_at": "2026-10-01T08:00:00",
                                    "marketing_carrier": {"iata_code": "ZZ"},
                                    "marketing_carrier_flight_number": "101",
                                    "passengers": [
                                        {
                                            "baggages": [
                                                {"type": "checked", "quantity": 1},
                                                {"type": "carry_on", "quantity": 1},
                                            ]
                                        }
                                    ],
                                },
                            ]
                        }
                    ],
                }
            ],
        }
    }


@respx.mock
def test_duffel_search_posts_offer_request_and_normalizes_offer() -> None:
    route = respx.post(f"{DUFFEL_API_BASE_URL}/air/offer_requests").mock(
        return_value=httpx.Response(201, json=_duffel_offer_response())
    )

    offers = asyncio.run(
        DuffelProvider().search(
            _request(),
            ProviderContext(credentials={"DUFFEL_TOKEN": "test-token"}, timeout_seconds=5),
        )
    )

    assert route.called
    sent_json = route.calls[0].request.content.decode()
    assert '"origin":"PVG"' in sent_json
    assert '"destination":"LAX"' in sent_json
    assert '"cabin_class":"business"' in sent_json
    assert route.calls[0].request.headers["Duffel-Version"] == "v2"
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-token"

    offer = offers[0]
    assert offer.provider == "duffel"
    assert offer.total_amount is not None
    assert str(offer.total_amount) == "1234.56"
    assert offer.ticketing_type == TicketingType.SINGLE_TICKET
    assert offer.segments[0].marketing_carrier == "ZZ"
    assert offer.segments[0].flight_number == "100"
    assert offer.travel_duration_minutes == 2055
    assert offer.layovers[0].airport == "HND"
    assert offer.layovers[0].duration_minutes == 150
    assert offer.baggage[0].included_checked_bags == 1
    assert offer.fare_rules[0].change_allowed is True
    assert offer.fare_rules[0].refund_allowed is False
    assert RiskFlag.PROVIDER_UNVERIFIED in offer.risk_flags


@respx.mock
def test_duffel_round_trip_request_includes_return_slice() -> None:
    route = respx.post(f"{DUFFEL_API_BASE_URL}/air/offer_requests").mock(
        return_value=httpx.Response(201, json={"data": {"offers": []}})
    )
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "return_date": "2026-10-10",
        }
    )

    asyncio.run(
        DuffelProvider().search(
            request,
            ProviderContext(credentials={"DUFFEL_TOKEN": "test-token"}, timeout_seconds=5),
        )
    )

    sent_json = route.calls[0].request.content.decode()
    assert '"origin":"PVG"' in sent_json
    assert '"destination":"LAX"' in sent_json
    assert '"origin":"LAX"' in sent_json
    assert '"destination":"PVG"' in sent_json


def test_duffel_requires_token() -> None:
    try:
        asyncio.run(DuffelProvider().search(_request(), ProviderContext()))
    except ProviderNotConfigured as exc:
        assert "DUFFEL_API_TOKEN" in str(exc)
    else:
        raise AssertionError("DuffelProvider should require a token")


@respx.mock
def test_duffel_api_error_is_structured() -> None:
    respx.post(f"{DUFFEL_API_BASE_URL}/air/offer_requests").mock(
        return_value=httpx.Response(
            401,
            json={"errors": [{"title": "Unauthorized", "message": "Invalid token"}]},
        )
    )

    try:
        asyncio.run(
            DuffelProvider().search(
                _request(),
                ProviderContext(credentials={"DUFFEL_TOKEN": "bad-token"}, timeout_seconds=5),
            )
        )
    except ProviderError as exc:
        assert "Unauthorized" in str(exc)
    else:
        raise AssertionError("DuffelProvider should raise ProviderError for API errors")
