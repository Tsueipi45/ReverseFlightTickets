"""Trip.com manual deep-link provider."""

from __future__ import annotations

from urllib.parse import urlencode

from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.providers.base import ManualDeepLinkProvider


class TripProvider(ManualDeepLinkProvider):
    name = "trip"

    def build_booking_link(self, request: SearchRequest) -> str:
        query = urlencode(
            {
                "dcity": request.origin,
                "acity": request.destination,
                "ddate": request.departure_date.isoformat(),
                "rdate": request.return_date.isoformat() if request.return_date else "",
                "adult": request.passengers.adults,
                "child": request.passengers.children,
                "curr": self._first_currency(request),
                "locale": self._first_market(request),
            }
        )
        return f"https://www.trip.com/flights/search?{query}"
