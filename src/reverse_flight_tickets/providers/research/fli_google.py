"""Google Flights research deep-link provider."""

from __future__ import annotations

from urllib.parse import quote_plus

from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.providers.base import ManualDeepLinkProvider, ProviderCapability


class GoogleFlightsResearchProvider(ManualDeepLinkProvider):
    """Manual Google Flights link reserved for fli/Google Flights research."""

    name = "google_flights_research"
    capabilities = ProviderCapability(
        supports_market=True,
        supports_currency=True,
        supports_booking_link=True,
        supports_deep_link=True,
        is_research=True,
    )

    def build_booking_link(self, request: SearchRequest) -> str:
        query = (
            f"Flights from {request.origin} to {request.destination} "
            f"on {request.departure_date.isoformat()}"
        )
        if request.return_date:
            query += f" returning {request.return_date.isoformat()}"
        return f"https://www.google.com/travel/flights?q={quote_plus(query)}"
