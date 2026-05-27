"""Fliggy manual deep-link provider."""

from __future__ import annotations

from urllib.parse import urlencode

from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.providers.base import ManualDeepLinkProvider


class FliggyProvider(ManualDeepLinkProvider):
    name = "fliggy"

    def build_booking_link(self, request: SearchRequest) -> str:
        query = urlencode(
            {
                "tripType": "1" if request.return_date else "0",
                "depCity": request.origin,
                "arrCity": request.destination,
                "depDate": request.departure_date.isoformat(),
                "retDate": request.return_date.isoformat() if request.return_date else "",
                "adultNum": request.passengers.adults,
                "childNum": request.passengers.children,
            }
        )
        return f"https://sjipiao.fliggy.com/flight_search_result.htm?{query}"
