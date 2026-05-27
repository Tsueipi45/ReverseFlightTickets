import asyncio

import httpx
import respx

from reverse_flight_tickets.domain import RiskFlag, SearchRequest, TicketingType
from reverse_flight_tickets.providers import AmadeusProvider, ProviderContext, ProviderNotConfigured
from reverse_flight_tickets.providers.amadeus import AMADEUS_API_BASE_URL
from reverse_flight_tickets.providers.base import ProviderError


def _request() -> SearchRequest:
    return SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "return_date": "2026-10-15",
            "passenger_count": 1,
            "cabin": "business",
            "allowed_markets": "US",
            "allowed_currencies": "USD",
        }
    )


def _amadeus_response() -> dict[str, object]:
    return {
        "data": [
            {
                "id": "1",
                "source": "GDS",
                "lastTicketingDate": "2026-09-01",
                "price": {
                    "currency": "USD",
                    "total": "890.00",
                    "grandTotal": "910.00",
                },
                "itineraries": [
                    {
                        "duration": "PT13H30M",
                        "segments": [
                            {
                                "departure": {"iataCode": "PVG", "at": "2026-10-01T12:30:00"},
                                "arrival": {"iataCode": "LAX", "at": "2026-10-01T10:00:00"},
                                "carrierCode": "MU",
                                "number": "583",
                            }
                        ],
                    },
                    {
                        "duration": "PT14H",
                        "segments": [
                            {
                                "departure": {"iataCode": "LAX", "at": "2026-10-15T12:00:00"},
                                "arrival": {"iataCode": "PVG", "at": "2026-10-16T18:00:00"},
                                "carrierCode": "MU",
                                "number": "586",
                            }
                        ],
                    },
                ],
            }
        ]
    }


@respx.mock
def test_amadeus_search_authenticates_and_normalizes_offer() -> None:
    token_route = respx.post(f"{AMADEUS_API_BASE_URL}/v1/security/oauth2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "access-token"})
    )
    search_route = respx.get(f"{AMADEUS_API_BASE_URL}/v2/shopping/flight-offers").mock(
        return_value=httpx.Response(200, json=_amadeus_response())
    )

    offers = asyncio.run(
        AmadeusProvider().search(
            _request(),
            ProviderContext(
                credentials={
                    "AMADEUS_CLIENT_ID": "client-id",
                    "AMADEUS_CLIENT_SECRET": "client-secret",
                },
                timeout_seconds=5,
            ),
        )
    )

    assert token_route.called
    assert search_route.called
    token_body = token_route.calls[0].request.content.decode()
    assert "grant_type=client_credentials" in token_body
    assert search_route.calls[0].request.headers["Authorization"] == "Bearer access-token"
    query = dict(search_route.calls[0].request.url.params)
    assert query["originLocationCode"] == "PVG"
    assert query["destinationLocationCode"] == "LAX"
    assert query["departureDate"] == "2026-10-01"
    assert query["returnDate"] == "2026-10-15"
    assert query["travelClass"] == "BUSINESS"

    offer = offers[0]
    assert offer.provider == "amadeus"
    assert str(offer.total_amount) == "910.00"
    assert offer.ticketing_type == TicketingType.SINGLE_TICKET
    assert offer.segments[0].marketing_carrier == "MU"
    assert offer.segments[0].flight_number == "583"
    assert offer.travel_duration_minutes == 1650
    assert RiskFlag.PROVIDER_UNVERIFIED in offer.risk_flags


def test_amadeus_requires_credentials() -> None:
    try:
        asyncio.run(AmadeusProvider().search(_request(), ProviderContext()))
    except ProviderNotConfigured as exc:
        assert "AMADEUS_CLIENT_ID" in str(exc)
    else:
        raise AssertionError("AmadeusProvider should require credentials")


@respx.mock
def test_amadeus_token_error_is_structured() -> None:
    respx.post(f"{AMADEUS_API_BASE_URL}/v1/security/oauth2/token").mock(
        return_value=httpx.Response(
            401,
            json={"error_description": "Invalid client credentials"},
        )
    )

    try:
        asyncio.run(
            AmadeusProvider().search(
                _request(),
                ProviderContext(
                    credentials={
                        "AMADEUS_CLIENT_ID": "bad",
                        "AMADEUS_CLIENT_SECRET": "bad",
                    },
                    timeout_seconds=5,
                ),
            )
        )
    except ProviderError as exc:
        assert "Invalid client credentials" in str(exc)
    else:
        raise AssertionError("AmadeusProvider should raise ProviderError for auth errors")
