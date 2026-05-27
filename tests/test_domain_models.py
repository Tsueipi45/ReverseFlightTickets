from datetime import date

from reverse_flight_tickets.domain import SearchRequest


def test_search_request_builds_default_segment() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "pvg",
            "destination": "lax",
            "departure_date": "2026-10-01",
            "allowed_markets": "us,cn",
            "allowed_currencies": "usd,cny",
        }
    )

    assert request.origin == "PVG"
    assert request.destination == "LAX"
    assert request.departure_date == date(2026, 10, 1)
    assert request.allowed_markets == ("US", "CN")
    assert request.allowed_currencies == ("USD", "CNY")
    assert request.segments[0].origin == "PVG"
