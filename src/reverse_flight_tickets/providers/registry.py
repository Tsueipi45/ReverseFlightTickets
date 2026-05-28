"""Provider registry shared by CLI, API, and future interfaces."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from reverse_flight_tickets.providers.amadeus import AmadeusProvider
from reverse_flight_tickets.providers.base import FlightProvider, ProviderCapability
from reverse_flight_tickets.providers.duffel import DuffelProvider
from reverse_flight_tickets.providers.fliggy import FliggyProvider
from reverse_flight_tickets.providers.research import (
    GoogleFlightsResearchProvider,
    KiwiResearchProvider,
    LetsFGResearchProvider,
)
from reverse_flight_tickets.providers.skyscanner import SkyscannerProvider
from reverse_flight_tickets.providers.trip import TripProvider

class ProviderFactory(Protocol):
    capabilities: ProviderCapability

    def __call__(self) -> FlightProvider:
        """Create a provider instance."""

PROVIDER_FACTORIES: dict[str, ProviderFactory] = {
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


def provider_names_for_request(
    provider_names: Iterable[str] = (),
    *,
    include_research: bool = False,
) -> tuple[str, ...]:
    names = tuple(provider_names) or DEFAULT_PROVIDER_NAMES
    if include_research:
        names = names + RESEARCH_PROVIDER_NAMES
    return names


def providers_from_names(
    provider_names: Iterable[str] = (),
    *,
    include_research: bool = False,
) -> tuple[FlightProvider, ...]:
    names = provider_names_for_request(provider_names, include_research=include_research)
    unknown = [name for name in names if name not in PROVIDER_FACTORIES]
    if unknown:
        raise ValueError(f"unknown provider(s): {', '.join(unknown)}")
    return tuple(PROVIDER_FACTORIES[name]() for name in names)


def available_provider_metadata() -> tuple[dict[str, object], ...]:
    metadata: list[dict[str, object]] = []
    for name, factory in PROVIDER_FACTORIES.items():
        capabilities = factory.capabilities
        metadata.append(
            {
                "name": name,
                "default_enabled": name in DEFAULT_PROVIDER_NAMES,
                "research": capabilities.is_research,
                "requires_credentials": capabilities.requires_credentials,
                "capabilities": capabilities.model_dump(mode="json"),
            }
        )
    return tuple(metadata)
