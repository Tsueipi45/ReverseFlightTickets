from reverse_flight_tickets.domain import RiskFlag, SearchRequest
from reverse_flight_tickets.providers import SkyscannerProvider, TripProvider


def test_skyscanner_deeplink_offer_marks_manual_check() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "allowed_markets": "US",
            "allowed_currencies": "USD",
        }
    )
    offer = __import__("asyncio").run(SkyscannerProvider().search(request))[0]

    assert "skyscanner.com" in (offer.booking_link or "")
    assert offer.manual_check_required is True
    assert RiskFlag.MANUAL_CHECK_REQUIRED in offer.risk_flags


def test_trip_deeplink_includes_return_date() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "return_date": "2026-10-10",
        }
    )
    link = TripProvider().build_booking_link(request)

    assert "rdate=2026-10-10" in link
