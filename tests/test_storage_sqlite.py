import asyncio
from decimal import Decimal
from pathlib import Path

from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.monitoring import WatchlistItem, build_price_trend_report
from reverse_flight_tickets.providers import SkyscannerProvider
from reverse_flight_tickets.search import SearchOrchestrator
from reverse_flight_tickets.storage import (
    SearchSnapshot,
    SqliteSearchRepository,
    SqliteWatchlistRepository,
)


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


def test_sqlite_repository_lists_snapshots_for_request(tmp_path: Path) -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
        }
    )
    result = asyncio.run(SearchOrchestrator([SkyscannerProvider()]).search(request))
    repository = SqliteSearchRepository(f"sqlite:///{tmp_path / 'snapshots.sqlite3'}")

    repository.save_search_snapshot(SearchSnapshot.from_search_result(result))
    snapshots = repository.list_search_snapshots(request)

    assert len(snapshots) == 1
    assert snapshots[0].request == request


def test_sqlite_watchlist_repository_round_trips_provider_names(tmp_path: Path) -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
        }
    )
    item = WatchlistItem(
        request=request,
        target_amount=Decimal("500.00"),
        target_currency="USD",
        provider_names=("skyscanner", "trip"),
    )
    repository = SqliteWatchlistRepository(f"sqlite:///{tmp_path / 'watchlist.sqlite3'}")

    item_id = repository.add(item)
    loaded = repository.get(item_id)

    assert loaded is not None
    assert loaded.request == request
    assert loaded.target_amount == Decimal("500.00")
    assert loaded.provider_names == ("skyscanner", "trip")


def test_price_trend_report_uses_snapshot_lowest_offer(tmp_path: Path) -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
        }
    )
    result = asyncio.run(SearchOrchestrator([SkyscannerProvider()]).search(request))
    repository = SqliteSearchRepository(f"sqlite:///{tmp_path / 'trends.sqlite3'}")
    repository.save_search_snapshot(SearchSnapshot.from_search_result(result))

    report = build_price_trend_report(repository.list_search_snapshots(request))

    assert report.points == ()
