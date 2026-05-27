from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.providers import SkyscannerProvider
from reverse_flight_tickets.search import SearchOrchestrator


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
