"""Kiwi/Nomad research deep-link provider."""

from __future__ import annotations

from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.providers.base import ManualDeepLinkProvider, ProviderCapability


class KiwiResearchProvider(ManualDeepLinkProvider):
    """Manual Kiwi link reserved for Nomad/self-transfer strategy research."""

    name = "kiwi_research"
    capabilities = ProviderCapability(
        supports_market=True,
        supports_currency=True,
        supports_booking_link=True,
        supports_deep_link=True,
        is_research=True,
    )

    def build_booking_link(self, request: SearchRequest) -> str:
        origin = request.origin.lower()
        destination = request.destination.lower()
        departure = request.departure_date.isoformat()
        return f"https://www.kiwi.com/en/search/results/{origin}/{destination}/{departure}"
