"""Command line interface for ReverseFlightTickets."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer

from reverse_flight_tickets.config import AppConfig
from reverse_flight_tickets.domain import SearchRequest
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
from reverse_flight_tickets.search import SearchOrchestrator, SearchRunResult
from reverse_flight_tickets.storage import SearchSnapshot, SqliteSearchRepository


app = typer.Typer(help="ReverseFlightTickets CLI")

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
    max_layover_hours: Annotated[int | None, typer.Option("--max-layover-hours")] = None,
    include_split_ticket: Annotated[bool, typer.Option("--include-split-ticket")] = False,
    include_self_transfer: Annotated[bool, typer.Option("--include-self-transfer")] = False,
    include_hidden_city: Annotated[bool, typer.Option("--include-hidden-city")] = False,
    provider: Annotated[
        list[str] | None,
        typer.Option("--provider", help="Provider to include; repeatable."),
    ] = None,
    include_research: Annotated[bool, typer.Option("--include-research")] = False,
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
            passenger_count=passenger_count,
            cabin=cabin,
            markets=markets,
            currencies=currencies,
            max_layover_hours=max_layover_hours,
            include_split_ticket=include_split_ticket,
            include_self_transfer=include_self_transfer,
            include_hidden_city=include_hidden_city,
            provider=tuple(provider or ()),
            include_research=include_research,
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


async def _run_search(
    *,
    json_input: Path | None = None,
    origin: str | None = None,
    destination: str | None = None,
    departure_date: str | None = None,
    return_date: str | None = None,
    passenger_count: int | None = None,
    cabin: str | None = None,
    markets: str | None = None,
    currencies: str | None = None,
    max_layover_hours: int | None = None,
    include_split_ticket: bool = False,
    include_self_transfer: bool = False,
    include_hidden_city: bool = False,
    provider: tuple[str, ...] = (),
    include_research: bool = False,
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
        passenger_count=passenger_count,
        cabin=cabin,
        markets=markets,
        currencies=currencies,
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
    )
    result = await orchestrator.search(request, context)
    if save_snapshot:
        repository = SqliteSearchRepository(db_url or config.database_url)
        snapshot_id = repository.save_search_snapshot(SearchSnapshot.from_search_result(result))
        result = result.model_copy(update={"warnings": result.warnings + (f"snapshot saved: {snapshot_id}",)})
    return result


def _request_from_values(
    *,
    config: AppConfig,
    json_input: Path | None,
    origin: str | None,
    destination: str | None,
    departure_date: str | None,
    return_date: str | None,
    passenger_count: int | None,
    cabin: str | None,
    markets: str | None,
    currencies: str | None,
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
        "passenger_count": passenger_count,
        "cabin": cabin,
        "allowed_markets": markets,
        "allowed_currencies": currencies,
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
            "ticketing",
            "risks",
            "booking_link",
        )
    ]
    for offer in result.offers:
        amount = str(offer.display_amount) if offer.display_amount is not None else "manual"
        risks = ",".join(flag.value for flag in offer.risk_flags) or "-"
        rows.append(
            (
                offer.provider,
                offer.source_market,
                offer.currency,
                amount,
                offer.ticketing_type.value,
                risks,
                offer.booking_link or "-",
            )
        )
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    lines = []
    for row_index, row in enumerate(rows):
        lines.append(" | ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
        if row_index == 0:
            lines.append("-+-".join("-" * width for width in widths))
    if result.recommendations.best_value:
        lines.append("")
        lines.append(f"Best value: {result.recommendations.best_value.provider}")
    if result.warnings:
        lines.append("")
        lines.extend(f"Warning: {warning}" for warning in result.warnings)
    return "\n".join(lines)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
