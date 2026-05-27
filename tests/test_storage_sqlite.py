import asyncio
from pathlib import Path

from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.providers import SkyscannerProvider
from reverse_flight_tickets.search import SearchOrchestrator
from reverse_flight_tickets.storage import SearchSnapshot, SqliteSearchRepository


def test_sqlite_repository_saves_and_loads_snapshot(tmp_path: Path) -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
        }
    )
    result = asyncio.run(SearchOrchestrator([SkyscannerProvider()]).search(request))
    snapshot = SearchSnapshot.from_search_result(result)
    repository = SqliteSearchRepository(f"sqlite:///{tmp_path / 'snapshots.sqlite3'}")

    snapshot_id = repository.save_search_snapshot(snapshot)
    loaded = repository.get_search_snapshot(snapshot_id)

    assert loaded is not None
    assert loaded.request.origin == "PVG"
    assert loaded.offers[0].offer.provider == "skyscanner"
    assert loaded.provider_runs[0].status == "ok"
