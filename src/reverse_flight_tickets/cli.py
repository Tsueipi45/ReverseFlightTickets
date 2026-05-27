"""Command line interface for ReverseFlightTickets."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from decimal import Decimal
from typing import Annotated, Any, Sequence, TypedDict

import typer

from reverse_flight_tickets.config import AppConfig
from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.monitoring import (
    PriceDropAlert,
    WatchlistItem,
    build_price_trend_report,
    evaluate_price_drop,
)
from reverse_flight_tickets.providers import (
    AmadeusProvider,
    DuffelProvider,
    FliggyProvider,
    FlightProvider,
    ProviderContext,
    SkyscannerProvider,
    TripProvider,
)
from reverse_flight_tickets.providers.research import (
    GoogleFlightsResearchProvider,
    KiwiResearchProvider,
    LetsFGResearchProvider,
)
from reverse_flight_tickets.search.filters import normalize_carrier_codes
from reverse_flight_tickets.search import SearchOrchestrator, SearchRunResult
from reverse_flight_tickets.storage import (
    SearchSnapshot,
    SqliteSearchRepository,
    SqliteWatchlistRepository,
)


app = typer.Typer(help="ReverseFlightTickets CLI")
watchlist_app = typer.Typer(help="Manage and run price watchlists")
app.add_typer(watchlist_app, name="watchlist")

PROVIDER_FACTORIES = {
    "skyscanner": SkyscannerProvider,
    "trip": TripProvider,
    "fliggy": FliggyProvider,
    "duffel": DuffelProvider,
    "amadeus": AmadeusProvider,
    "google_flights_research": GoogleFlightsResearchProvider,
    "kiwi_research": KiwiResearchProvider,
    "letsfg_research": LetsFGResearchProvider,
}
DEFAULT_PROVIDER_NAMES = ("skyscanner", "trip", "fliggy")
RESEARCH_PROVIDER_NAMES = ("google_flights_research", "kiwi_research")
DEFAULT_EXCLUDED_CARRIERS = ("ZZ",)


class WatchlistRunRecord(TypedDict):
    item_id: str
    snapshot_id: str
    offer_count: int
    alerts: list[dict[str, str]]
    trend: dict[str, object]
    warnings: list[str]


@app.callback()
def _root() -> None:
    """ReverseFlightTickets command group."""


@app.command()
def search(
    json_input: Annotated[
        Path | None,
        typer.Option("--json-input", help="Path to a SearchRequest JSON file"),
    ] = None,
    origin: Annotated[str | None, typer.Option(help="Origin airport/city code")] = None,
    destination: Annotated[str | None, typer.Option(help="Destination airport/city code")] = None,
    departure_date: Annotated[
        str | None,
        typer.Option("--departure-date", help="Departure date, YYYY-MM-DD"),
    ] = None,
    return_date: Annotated[
        str | None,
        typer.Option("--return-date", help="Return date, YYYY-MM-DD"),
    ] = None,
    date_flexibility_days: Annotated[
        int,
        typer.Option(
            "--date-flexibility-days",
            min=0,
            help="Search +/- N days around the requested departure/return dates.",
        ),
    ] = 0,
    passenger_count: Annotated[
        int | None,
        typer.Option("--passenger-count", help="Adult passenger count"),
    ] = None,
    cabin: Annotated[
        str | None,
        typer.Option(help="Cabin: economy, premium_economy, business, first"),
    ] = None,
    markets: Annotated[
        str | None,
        typer.Option("--markets", help="Comma-separated point-of-sale markets, e.g. US,CN"),
    ] = None,
    currencies: Annotated[
        str | None,
        typer.Option("--currencies", help="Comma-separated currencies, e.g. USD,CNY"),
    ] = None,
    stopover: Annotated[
        list[str] | None,
        typer.Option(
            "--stopover",
            help="Stopover airport/city code for generated multi-city candidates; repeatable.",
        ),
    ] = None,
    max_layover_hours: Annotated[int | None, typer.Option("--max-layover-hours")] = None,
    include_split_ticket: Annotated[bool, typer.Option("--include-split-ticket")] = False,
    include_self_transfer: Annotated[bool, typer.Option("--include-self-transfer")] = False,
    include_hidden_city: Annotated[bool, typer.Option("--include-hidden-city")] = False,
    provider: Annotated[
        list[str] | None,
        typer.Option("--provider", help="Provider to include; repeatable."),
    ] = None,
    include_research: Annotated[bool, typer.Option("--include-research")] = False,
    exclude_carrier: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-carrier",
            help="Carrier code to filter locally; repeatable. Duffel sandbox ZZ is excluded by default.",
        ),
    ] = None,
    include_test_carriers: Annotated[
        bool,
        typer.Option(
            "--include-test-carriers",
            help="Show sandbox/test carriers such as Duffel Airways ZZ.",
        ),
    ] = False,
    output: Annotated[
        str,
        typer.Option("--output", help="Output format: table or json"),
    ] = "table",
    save_snapshot: Annotated[bool, typer.Option("--save-snapshot")] = False,
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", help="SQLAlchemy database URL for snapshots"),
    ] = None,
) -> None:
    """Search flight offers through configured providers."""

    result = asyncio.run(
        _run_search(
            json_input=json_input,
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            date_flexibility_days=date_flexibility_days,
            passenger_count=passenger_count,
            cabin=cabin,
            markets=markets,
            currencies=currencies,
            stopover=tuple(stopover or ()),
            max_layover_hours=max_layover_hours,
            include_split_ticket=include_split_ticket,
            include_self_transfer=include_self_transfer,
            include_hidden_city=include_hidden_city,
            provider=tuple(provider or ()),
            include_research=include_research,
            exclude_carrier=tuple(exclude_carrier or ()),
            include_test_carriers=include_test_carriers,
            save_snapshot=save_snapshot,
            db_url=db_url,
        )
    )
    if output == "json":
        typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif output == "table":
        typer.echo(_format_table(result))
    else:
        raise typer.BadParameter("output must be table or json")


@watchlist_app.command("add")
def watchlist_add(
    json_input: Annotated[
        Path | None,
        typer.Option("--json-input", help="Path to a SearchRequest JSON file"),
    ] = None,
    origin: Annotated[str | None, typer.Option(help="Origin airport/city code")] = None,
    destination: Annotated[str | None, typer.Option(help="Destination airport/city code")] = None,
    departure_date: Annotated[
        str | None,
        typer.Option("--departure-date", help="Departure date, YYYY-MM-DD"),
    ] = None,
    return_date: Annotated[
        str | None,
        typer.Option("--return-date", help="Return date, YYYY-MM-DD"),
    ] = None,
    target_amount: Annotated[
        str | None,
        typer.Option("--target-amount", help="Alert threshold amount"),
    ] = None,
    target_currency: Annotated[
        str | None,
        typer.Option("--target-currency", help="Alert threshold currency"),
    ] = None,
    provider: Annotated[
        list[str] | None,
        typer.Option("--provider", help="Provider to include when running this watchlist item."),
    ] = None,
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", help="SQLAlchemy database URL for watchlists"),
    ] = None,
) -> None:
    """Add a search request to the local watchlist."""

    config = AppConfig.from_env()
    request = _request_from_values(
        config=config,
        json_input=json_input,
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        date_flexibility_days=0,
        passenger_count=None,
        cabin=None,
        markets=None,
        currencies=None,
        stopover=(),
        max_layover_hours=None,
        include_split_ticket=False,
        include_self_transfer=False,
        include_hidden_city=False,
    )
    item = WatchlistItem(
        request=request,
        target_amount=Decimal(target_amount) if target_amount else None,
        target_currency=target_currency.upper() if target_currency else None,
        provider_names=tuple(provider or ()),
    )
    repository = SqliteWatchlistRepository(db_url or config.database_url)
    typer.echo(repository.add(item))


@watchlist_app.command("list")
def watchlist_list(
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", help="SQLAlchemy database URL for watchlists"),
    ] = None,
    output: Annotated[str, typer.Option("--output", help="Output format: table or json")] = "table",
) -> None:
    """List local watchlist items."""

    config = AppConfig.from_env()
    repository = SqliteWatchlistRepository(db_url or config.database_url)
    items = repository.list()
    if output == "json":
        typer.echo(json.dumps([item.to_dict() for item in items], ensure_ascii=False, indent=2))
        return
    if output != "table":
        raise typer.BadParameter("output must be table or json")
    if not items:
        typer.echo("No watchlist items.")
        return
    rows = [("item_id", "origin", "destination", "departure", "target", "providers")]
    for item in items:
        target = (
            f"{item.target_amount} {item.target_currency or item.request.allowed_currencies[0]}"
            if item.target_amount is not None
            else "-"
        )
        rows.append(
            (
                item.item_id,
                item.request.origin,
                item.request.destination,
                item.request.departure_date.isoformat(),
                target,
                ",".join(item.provider_names) if item.provider_names else "-",
            )
        )
    typer.echo(_format_rows(rows))


@watchlist_app.command("run")
def watchlist_run(
    item_id: Annotated[
        str | None,
        typer.Option("--item-id", help="Run a single watchlist item by id"),
    ] = None,
    provider: Annotated[
        list[str] | None,
        typer.Option("--provider", help="Override providers for this run; repeatable."),
    ] = None,
    include_research: Annotated[bool, typer.Option("--include-research")] = False,
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", help="SQLAlchemy database URL for watchlists and snapshots"),
    ] = None,
    output: Annotated[str, typer.Option("--output", help="Output format: table or json")] = "table",
) -> None:
    """Run local watchlist items once and persist snapshots."""

    results = asyncio.run(
        _run_watchlist(
            item_id=item_id,
            provider=tuple(provider or ()),
            include_research=include_research,
            db_url=db_url,
        )
    )
    if output == "json":
        typer.echo(json.dumps(results, ensure_ascii=False, indent=2))
        return
    if output != "table":
        raise typer.BadParameter("output must be table or json")
    if not results:
        typer.echo("No watchlist items to run.")
        return
    rows = [("item_id", "snapshot_id", "offers", "alert", "latest", "change")]
    for result in results:
        alerts = result["alerts"]
        alert = alerts[0] if isinstance(alerts, list) and alerts else None
        trend = result["trend"]
        latest = trend["latest"] if isinstance(trend, dict) else None
        rows.append(
            (
                str(result["item_id"]),
                str(result["snapshot_id"]),
                str(result["offer_count"]),
                f"{alert['amount']} {alert['currency']}" if isinstance(alert, dict) else "-",
                f"{latest['lowest_amount']} {latest['currency']}" if isinstance(latest, dict) else "-",
                str(trend.get("change_from_previous") or "-") if isinstance(trend, dict) else "-",
            )
        )
    typer.echo(_format_rows(rows))


@watchlist_app.command("schedule")
def watchlist_schedule(
    interval_seconds: Annotated[
        int,
        typer.Option("--interval-seconds", min=1, help="Seconds between watchlist runs."),
    ] = 3600,
    iterations: Annotated[
        int | None,
        typer.Option(
            "--iterations",
            min=1,
            help="Number of runs before exiting. Omit to run until interrupted.",
        ),
    ] = None,
    item_id: Annotated[
        str | None,
        typer.Option("--item-id", help="Run a single watchlist item by id"),
    ] = None,
    provider: Annotated[
        list[str] | None,
        typer.Option("--provider", help="Override providers for each run; repeatable."),
    ] = None,
    include_research: Annotated[bool, typer.Option("--include-research")] = False,
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", help="SQLAlchemy database URL for watchlists and snapshots"),
    ] = None,
) -> None:
    """Run watchlist checks on a simple local interval."""

    summaries = asyncio.run(
        _schedule_watchlist(
            interval_seconds=interval_seconds,
            iterations=iterations,
            item_id=item_id,
            provider=tuple(provider or ()),
            include_research=include_research,
            db_url=db_url,
        )
    )
    for index, summary in enumerate(summaries, start=1):
        typer.echo(
            f"run {index}: {summary['item_count']} item(s), "
            f"{summary['alert_count']} alert(s), {summary['snapshot_count']} snapshot(s)"
        )


async def _run_search(
    *,
    json_input: Path | None = None,
    origin: str | None = None,
    destination: str | None = None,
    departure_date: str | None = None,
    return_date: str | None = None,
    date_flexibility_days: int = 0,
    passenger_count: int | None = None,
    cabin: str | None = None,
    markets: str | None = None,
    currencies: str | None = None,
    stopover: tuple[str, ...] = (),
    max_layover_hours: int | None = None,
    include_split_ticket: bool = False,
    include_self_transfer: bool = False,
    include_hidden_city: bool = False,
    provider: tuple[str, ...] = (),
    include_research: bool = False,
    exclude_carrier: tuple[str, ...] = (),
    include_test_carriers: bool = False,
    save_snapshot: bool = False,
    db_url: str | None = None,
) -> SearchRunResult:
    config = AppConfig.from_env()
    request = _request_from_values(
        config=config,
        json_input=json_input,
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        date_flexibility_days=date_flexibility_days,
        passenger_count=passenger_count,
        cabin=cabin,
        markets=markets,
        currencies=currencies,
        stopover=stopover,
        max_layover_hours=max_layover_hours,
        include_split_ticket=include_split_ticket,
        include_self_transfer=include_self_transfer,
        include_hidden_city=include_hidden_city,
    )
    providers = _providers_from_names(provider, include_research=include_research)
    context = ProviderContext(
        credentials=config.provider_secret_map(),
        timeout_seconds=config.provider_timeout_seconds,
    )
    orchestrator = SearchOrchestrator(
        providers,
        timeout_seconds=config.provider_timeout_seconds,
        excluded_carriers=_excluded_carriers(
            exclude_carrier=exclude_carrier,
            include_test_carriers=include_test_carriers,
        ),
        exchange_rates=dict(config.exchange_rates),
        payment_fee_rate=config.payment_fee_rate,
        baggage_fee_amount=config.baggage_fee_amount,
    )
    result = await orchestrator.search(request, context)
    if save_snapshot:
        repository = SqliteSearchRepository(db_url or config.database_url)
        snapshot_id = repository.save_search_snapshot(SearchSnapshot.from_search_result(result))
        result = result.model_copy(update={"warnings": result.warnings + (f"snapshot saved: {snapshot_id}",)})
    return result


async def _run_watchlist(
    *,
    item_id: str | None = None,
    provider: tuple[str, ...] = (),
    include_research: bool = False,
    db_url: str | None = None,
) -> list[WatchlistRunRecord]:
    config = AppConfig.from_env()
    database_url = db_url or config.database_url
    watchlist_repository = SqliteWatchlistRepository(database_url)
    snapshot_repository = SqliteSearchRepository(database_url)
    items = watchlist_repository.list()
    if item_id:
        items = tuple(item for item in items if item.item_id == item_id)

    context = ProviderContext(
        credentials=config.provider_secret_map(),
        timeout_seconds=config.provider_timeout_seconds,
    )
    results: list[WatchlistRunRecord] = []
    for item in items:
        provider_names = provider or item.provider_names
        providers = _providers_from_names(provider_names, include_research=include_research)
        orchestrator = SearchOrchestrator(
            providers,
            timeout_seconds=config.provider_timeout_seconds,
            excluded_carriers=DEFAULT_EXCLUDED_CARRIERS,
            exchange_rates=dict(config.exchange_rates),
            payment_fee_rate=config.payment_fee_rate,
            baggage_fee_amount=config.baggage_fee_amount,
        )
        search_result = await orchestrator.search(item.request, context)
        snapshot = SearchSnapshot.from_search_result(search_result)
        snapshot_id = snapshot_repository.save_search_snapshot(snapshot)
        alerts = _watchlist_alerts(item, search_result)
        trend = build_price_trend_report(
            snapshot_repository.list_search_snapshots(item.request)
        )
        results.append(
            {
                "item_id": item.item_id,
                "snapshot_id": snapshot_id,
                "offer_count": len(search_result.offers),
                "alerts": [alert.to_dict() for alert in alerts],
                "trend": trend.to_dict(),
                "warnings": list(search_result.warnings),
            }
        )
    return results


async def _schedule_watchlist(
    *,
    interval_seconds: int,
    iterations: int | None = None,
    item_id: str | None = None,
    provider: tuple[str, ...] = (),
    include_research: bool = False,
    db_url: str | None = None,
) -> list[dict[str, int]]:
    summaries: list[dict[str, int]] = []
    run_count = 0
    while iterations is None or run_count < iterations:
        results = await _run_watchlist(
            item_id=item_id,
            provider=provider,
            include_research=include_research,
            db_url=db_url,
        )
        summaries.append(
            {
                "item_count": len(results),
                "alert_count": sum(len(result["alerts"]) for result in results),
                "snapshot_count": sum(1 for result in results if result.get("snapshot_id")),
            }
        )
        run_count += 1
        if iterations is not None and run_count >= iterations:
            break
        await asyncio.sleep(interval_seconds)
    return summaries


def _watchlist_alerts(
    item: WatchlistItem,
    result: SearchRunResult,
) -> tuple[PriceDropAlert, ...]:
    if item.target_amount is None:
        return ()
    alerts = []
    for offer in result.offers:
        if item.target_currency and offer.currency != item.target_currency:
            continue
        alert = evaluate_price_drop(offer, item.target_amount)
        if alert:
            alerts.append(alert)
    return tuple(alerts)


def _excluded_carriers(
    *,
    exclude_carrier: tuple[str, ...],
    include_test_carriers: bool,
) -> tuple[str, ...]:
    carriers: tuple[str, ...] = () if include_test_carriers else DEFAULT_EXCLUDED_CARRIERS
    return normalize_carrier_codes(carriers + exclude_carrier)


def _request_from_values(
    *,
    config: AppConfig,
    json_input: Path | None,
    origin: str | None,
    destination: str | None,
    departure_date: str | None,
    return_date: str | None,
    date_flexibility_days: int,
    passenger_count: int | None,
    cabin: str | None,
    markets: str | None,
    currencies: str | None,
    stopover: tuple[str, ...],
    max_layover_hours: int | None,
    include_split_ticket: bool,
    include_self_transfer: bool,
    include_hidden_city: bool,
) -> SearchRequest:
    data: dict[str, Any] = {}
    if json_input:
        data.update(json.loads(json_input.read_text(encoding="utf-8")))

    overrides = {
        "origin": origin,
        "destination": destination,
        "departure_date": departure_date,
        "return_date": return_date,
        "date_flexibility_days": date_flexibility_days,
        "passenger_count": passenger_count,
        "cabin": cabin,
        "allowed_markets": markets,
        "allowed_currencies": currencies,
        "stopovers": stopover,
        "max_layover_hours": max_layover_hours,
    }
    data.update({key: value for key, value in overrides.items() if value not in (None, "")})
    if include_split_ticket:
        data["include_split_ticket"] = True
    if include_self_transfer:
        data["include_self_transfer"] = True
    if include_hidden_city:
        data["include_hidden_city"] = True

    return SearchRequest.from_mapping(
        data,
        default_markets=config.default_markets,
        default_currencies=config.default_currencies,
    )


def _providers_from_names(
    provider_names: tuple[str, ...],
    *,
    include_research: bool,
) -> tuple[FlightProvider, ...]:
    names = provider_names or DEFAULT_PROVIDER_NAMES
    if include_research:
        names = names + RESEARCH_PROVIDER_NAMES
    unknown = [name for name in names if name not in PROVIDER_FACTORIES]
    if unknown:
        raise typer.BadParameter(f"unknown provider(s): {', '.join(unknown)}")
    return tuple(PROVIDER_FACTORIES[name]() for name in names)


def _format_table(result: SearchRunResult) -> str:
    if not result.offers:
        lines = ["No offers returned.", "", "Provider status:"]
        lines.extend(
            f"- {run.provider} [{run.variant.source_market}/{run.variant.currency}]: "
            f"{run.status}{' - ' + run.error if run.error else ''}"
            for run in result.provider_runs
        )
        if result.warnings:
            lines.append("")
            lines.extend(f"Warning: {warning}" for warning in result.warnings)
        return "\n".join(lines)

    rows = [
        (
            "provider",
            "market",
            "currency",
            "amount",
            "airlines",
            "flights",
            "depart",
            "arrive",
            "travel_time",
            "transfers",
            "layover_time",
            "ticketing",
            "risks",
            "booking_link",
        )
    ]
    for offer in result.offers:
        amount = str(offer.display_amount) if offer.display_amount is not None else "manual"
        airlines = _format_airlines(offer)
        flights = _format_flights(offer)
        depart = _format_departure(offer)
        arrive = _format_arrival(offer)
        travel_time = _format_minutes(offer.travel_duration_minutes)
        transfers = _format_transfers(offer)
        layover_time = _format_layover_time(offer)
        risks = ",".join(flag.value for flag in offer.risk_flags) or "-"
        rows.append(
            (
                offer.provider,
                offer.source_market,
                offer.currency,
                amount,
                airlines,
                flights,
                depart,
                arrive,
                travel_time,
                transfers,
                layover_time,
                offer.ticketing_type.value,
                risks,
                offer.booking_link or "-",
            )
        )
    lines = _format_rows(rows).splitlines()
    if result.recommendations.best_value:
        lines.append("")
        lines.append(f"Best value: {result.recommendations.best_value.provider}")
    if result.warnings:
        lines.append("")
        lines.extend(f"Warning: {warning}" for warning in result.warnings)
    return "\n".join(lines)


def _format_rows(rows: Sequence[Sequence[str]]) -> str:
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    lines = []
    for row_index, row in enumerate(rows):
        lines.append(" | ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
        if row_index == 0:
            lines.append("-+-".join("-" * width for width in widths))
    return "\n".join(lines)


def _format_airlines(offer: object) -> str:
    carriers: list[str] = []
    for segment in getattr(offer, "segments", ()):
        carrier = getattr(segment, "marketing_carrier", None)
        if carrier and carrier not in carriers:
            carriers.append(carrier)
    return ",".join(carriers) if carriers else "-"


def _format_flights(offer: object) -> str:
    flights: list[str] = []
    for segment in getattr(offer, "segments", ()):
        carrier = getattr(segment, "marketing_carrier", None)
        flight_number = getattr(segment, "flight_number", None)
        if carrier and flight_number:
            flights.append(f"{carrier}{flight_number}")
        elif carrier:
            flights.append(carrier)
    return ",".join(flights) if flights else "-"


def _format_departure(offer: object) -> str:
    segments = tuple(getattr(offer, "segments", ()))
    if not segments:
        return "-"
    first_segment = segments[0]
    departure_time = getattr(first_segment, "departure_time", None)
    if departure_time:
        return str(departure_time)
    departure_date = getattr(first_segment, "departure_date", None)
    return str(departure_date) if departure_date else "-"


def _format_arrival(offer: object) -> str:
    segments = tuple(getattr(offer, "segments", ()))
    if not segments:
        return "-"
    last_segment = segments[-1]
    arrival_time = getattr(last_segment, "arrival_time", None)
    if arrival_time:
        return str(arrival_time)
    arrival_date = getattr(last_segment, "departure_date", None)
    return str(arrival_date) if arrival_date else "-"


def _format_transfers(offer: object) -> str:
    airports: list[str] = []
    for layover in getattr(offer, "layovers", ()):
        airport = getattr(layover, "airport", None)
        if airport:
            airports.append(airport)
    return ",".join(airports) if airports else "-"


def _format_layover_time(offer: object) -> str:
    formatted: list[str] = []
    for layover in getattr(offer, "layovers", ()):
        airport = getattr(layover, "airport", None)
        duration = getattr(layover, "duration_minutes", None)
        if airport and duration is not None:
            formatted.append(f"{airport} {_format_minutes(duration)}")
        elif airport:
            formatted.append(str(airport))
    return ",".join(formatted) if formatted else "-"


def _format_minutes(minutes: int | None) -> str:
    if minutes is None:
        return "-"
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours}h{remainder:02d}m"
    if hours:
        return f"{hours}h"
    return f"{remainder}m"


def main() -> None:
    app()


if __name__ == "__main__":
    main()
