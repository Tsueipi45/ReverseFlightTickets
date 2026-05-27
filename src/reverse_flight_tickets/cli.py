"""Command line interface for ReverseFlightTickets."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Sequence

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


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "search":
        asyncio.run(run_search(args))
        return
    parser.print_help()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rft")
    subparsers = parser.add_subparsers(dest="command")

    search = subparsers.add_parser("search", help="Search flight offers through configured providers")
    search.add_argument("--json-input", type=Path, help="Path to a SearchRequest JSON file")
    search.add_argument("--origin", help="Origin airport/city code")
    search.add_argument("--destination", help="Destination airport/city code")
    search.add_argument("--departure-date", help="Departure date, YYYY-MM-DD")
    search.add_argument("--return-date", help="Return date, YYYY-MM-DD")
    search.add_argument("--passenger-count", type=int, help="Adult passenger count")
    search.add_argument(
        "--cabin",
        choices=("economy", "premium_economy", "business", "first"),
        help="Cabin class",
    )
    search.add_argument("--markets", help="Comma-separated point-of-sale markets, e.g. US,CN")
    search.add_argument("--currencies", help="Comma-separated currencies, e.g. USD,CNY")
    search.add_argument("--max-layover-hours", type=int)
    search.add_argument("--include-split-ticket", action="store_true")
    search.add_argument("--include-self-transfer", action="store_true")
    search.add_argument("--include-hidden-city", action="store_true")
    search.add_argument(
        "--provider",
        action="append",
        choices=tuple(PROVIDER_FACTORIES),
        help="Provider to include; repeatable. Defaults to manual deep-link providers.",
    )
    search.add_argument("--include-research", action="store_true")
    search.add_argument("--output", choices=("table", "json"), default="table")
    return parser


async def run_search(args: argparse.Namespace) -> None:
    config = AppConfig.from_env()
    request = _request_from_args(args, config)
    providers = _providers_from_args(args)
    context = ProviderContext(
        credentials=config.provider_secret_map(),
        timeout_seconds=config.provider_timeout_seconds,
    )
    orchestrator = SearchOrchestrator(
        providers,
        timeout_seconds=config.provider_timeout_seconds,
    )
    result = await orchestrator.search(request, context)
    if args.output == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(_format_table(result))


def _request_from_args(args: argparse.Namespace, config: AppConfig) -> SearchRequest:
    data: dict[str, Any] = {}
    if args.json_input:
        data.update(json.loads(args.json_input.read_text(encoding="utf-8")))

    overrides = {
        "origin": args.origin,
        "destination": args.destination,
        "departure_date": args.departure_date,
        "return_date": args.return_date,
        "passenger_count": args.passenger_count,
        "cabin": args.cabin,
        "allowed_markets": args.markets,
        "allowed_currencies": args.currencies,
        "max_layover_hours": args.max_layover_hours,
    }
    data.update({key: value for key, value in overrides.items() if value not in (None, "")})
    if args.include_split_ticket:
        data["include_split_ticket"] = True
    if args.include_self_transfer:
        data["include_self_transfer"] = True
    if args.include_hidden_city:
        data["include_hidden_city"] = True

    return SearchRequest.from_mapping(
        data,
        default_markets=config.default_markets,
        default_currencies=config.default_currencies,
    )


def _providers_from_args(args: argparse.Namespace) -> tuple[FlightProvider, ...]:
    provider_names = tuple(args.provider or DEFAULT_PROVIDER_NAMES)
    if args.include_research:
        provider_names = provider_names + RESEARCH_PROVIDER_NAMES
    return tuple(PROVIDER_FACTORIES[name]() for name in provider_names)


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
    if result.warnings:
        lines.append("")
        lines.extend(f"Warning: {warning}" for warning in result.warnings)
    return "\n".join(lines)


if __name__ == "__main__":
    main()
