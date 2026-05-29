import asyncio
from decimal import Decimal
from pathlib import Path

import pytest

from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.domain import Offer
from reverse_flight_tickets.monitoring import WatchlistItem, build_price_trend_report
from reverse_flight_tickets.providers import SkyscannerProvider
from reverse_flight_tickets.search import SearchOrchestrator
from reverse_flight_tickets.storage import (
    OfferSnapshot,
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


def test_sqlite_repository_lists_route_snapshots_across_markets(tmp_path: Path) -> None:
    us_request = SearchRequest.from_mapping(
        {
            "origin": "SHA",
            "destination": "TPE",
            "departure_date": "2026-06-02",
            "return_date": "2026-06-12",
            "allowed_markets": ["US"],
            "allowed_currencies": ["USD"],
        }
    )
    cn_request = SearchRequest.from_mapping(
        {
            "origin": "SHA",
            "destination": "TPE",
            "departure_date": "2026-06-02",
            "return_date": "2026-06-12",
            "allowed_markets": ["CN"],
            "allowed_currencies": ["CNY"],
        }
    )
    repository = SqliteSearchRepository(f"sqlite:///{tmp_path / 'routes.sqlite3'}")
    repository.save_search_snapshot(
        SearchSnapshot(
            request=cn_request,
            offers=(
                OfferSnapshot(
                    offer=Offer(
                        provider="fliggy-browser",
                        source_market="CN",
                        currency="CNY",
                        total_amount="2225",
                    )
                ),
            ),
        )
    )

    snapshots = repository.list_route_snapshots(us_request)

    assert len(snapshots) == 1
    assert snapshots[0].offers[0].offer.provider == "fliggy-browser"


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


def test_sqlite_repository_rejects_non_sqlite_url() -> None:
    with pytest.raises(ValueError, match="only sqlite"):
        SqliteSearchRepository("postgresql://example/test")


def test_sqlite_repository_rejects_network_location() -> None:
    with pytest.raises(ValueError, match="network location"):
        SqliteWatchlistRepository("sqlite://remote/path.sqlite3")
