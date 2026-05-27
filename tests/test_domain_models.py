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


def test_search_request_builds_return_segment() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "return_date": "2026-10-10",
        }
    )

    assert len(request.segments) == 2
    assert request.segments[1].origin == "LAX"
    assert request.segments[1].destination == "PVG"


def test_search_request_shifts_dates_for_flexible_search() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "return_date": "2026-10-10",
            "date_flexibility_days": 2,
        }
    )

    shifted = request.with_date_shift(-1)

    assert shifted.departure_date == date(2026, 9, 30)
    assert shifted.return_date == date(2026, 10, 9)
    assert shifted.segments[0].departure_date == date(2026, 9, 30)
    assert shifted.segments[1].departure_date == date(2026, 10, 9)


def test_search_request_normalizes_stopovers() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "stopovers": "hnd, icn",
        }
    )

    assert request.stopovers == ("HND", "ICN")
