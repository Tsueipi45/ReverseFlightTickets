"""Skyscanner manual deep-link provider."""

from __future__ import annotations

from urllib.parse import urlencode

from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.providers.base import ManualDeepLinkProvider


class SkyscannerProvider(ManualDeepLinkProvider):
    name = "skyscanner"

    def build_booking_link(self, request: SearchRequest) -> str:
        query = urlencode(
            {
                "adultsv2": request.passengers.adults,
                "childrenv2": request.passengers.children,
                "cabinclass": request.cabin,
                "currency": self._first_currency(request),
                "market": self._first_market(request),
            }
        )
        origin = request.origin.lower()
        destination = request.destination.lower()
        departure = request.departure_date.isoformat()
        if request.return_date:
            return_date = request.return_date.isoformat()
            return (
                "https://www.skyscanner.com/transport/flights/"
                f"{origin}/{destination}/{departure}/{return_date}/?{query}"
            )
        return (
            "https://www.skyscanner.com/transport/flights/"
            f"{origin}/{destination}/{departure}/?{query}"
        )
