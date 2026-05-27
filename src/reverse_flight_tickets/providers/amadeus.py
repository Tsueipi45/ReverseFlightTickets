"""Amadeus Self-Service Flight Offers provider."""

from __future__ import annotations

from datetime import datetime, timedelta
from time import perf_counter
from typing import Any, Mapping, Sequence

import httpx

from reverse_flight_tickets.domain import (
    Offer,
    ProviderQuote,
    RiskFlag,
    SearchRequest,
    Segment,
    TicketingType,
)
from reverse_flight_tickets.providers.base import (
    BaseProvider,
    ProviderCapability,
    ProviderContext,
    ProviderError,
    ProviderNotConfigured,
)

AMADEUS_API_BASE_URL = "https://test.api.amadeus.com"


class AmadeusProvider(BaseProvider):
    """Amadeus Self-Service Flight Offers Search connector."""

    name = "amadeus"
    capabilities = ProviderCapability(
        supports_multi_city=False,
        supports_market=True,
        supports_currency=True,
        supports_booking_link=False,
        supports_order=True,
        requires_credentials=True,
    )

    async def search(
        self,
        request: SearchRequest,
        context: ProviderContext | None = None,
    ) -> Sequence[Offer]:
        client_id = self._credential(context, "AMADEUS_CLIENT_ID")
        client_secret = self._credential(context, "AMADEUS_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise ProviderNotConfigured("Amadeus requires AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET")

        timeout = context.timeout_seconds if context else 20.0
        started_at = perf_counter()
        async with httpx.AsyncClient(base_url=AMADEUS_API_BASE_URL, timeout=timeout) as client:
            token = await self._access_token(client, client_id, client_secret)
            response = await client.get(
                "/v2/shopping/flight-offers",
                params=self._search_params(request),
                headers={"Authorization": f"Bearer {token}"},
            )
        latency_ms = int((perf_counter() - started_at) * 1000)

        if response.status_code >= 400:
            raise ProviderError(self._error_message(response))

        body = response.json()
        data = body.get("data", [])
        if not isinstance(data, list):
            raise ProviderError("Amadeus response did not include a data list")

        return tuple(
            self._offer_from_amadeus(raw_offer, request=request, latency_ms=latency_ms)
            for raw_offer in data
            if isinstance(raw_offer, Mapping)
        )

    async def _access_token(
        self,
        client: httpx.AsyncClient,
        client_id: str,
        client_secret: str,
    ) -> str:
        response = await client.post(
            "/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code >= 400:
            raise ProviderError(self._error_message(response))
        body = response.json()
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise ProviderError("Amadeus token response did not include access_token")
        return token

    def _search_params(self, request: SearchRequest) -> dict[str, str | int | bool]:
        params: dict[str, str | int | bool] = {
            "originLocationCode": request.origin,
            "destinationLocationCode": request.destination,
            "departureDate": request.departure_date.isoformat(),
            "adults": request.passengers.adults,
            "currencyCode": self._first_currency(request),
            "nonStop": False,
            "max": 25,
        }
        if request.return_date:
            params["returnDate"] = request.return_date.isoformat()
        if request.passengers.children:
            params["children"] = request.passengers.children
        if request.passengers.infants:
            params["infants"] = request.passengers.infants
        travel_class = self._travel_class(request.cabin)
        if travel_class:
            params["travelClass"] = travel_class
        return params

    def _offer_from_amadeus(
        self,
        raw_offer: Mapping[str, Any],
        *,
        request: SearchRequest,
        latency_ms: int,
    ) -> Offer:
        price = raw_offer.get("price")
        price_data: Mapping[str, Any] = price if isinstance(price, Mapping) else {}
        currency = str(price_data.get("currency") or self._first_currency(request))
        total_amount = price_data.get("grandTotal") or price_data.get("total")
        segments = self._segments_from_offer(raw_offer, request)
        quote = ProviderQuote(
            provider=self.name,
            status="ok",
            raw={
                "id": raw_offer.get("id"),
                "source": raw_offer.get("source"),
                "lastTicketingDate": raw_offer.get("lastTicketingDate"),
            },
            latency_ms=latency_ms,
        )

        return Offer(
            provider=self.name,
            source_market=self._first_market(request),
            currency=currency,
            total_amount=total_amount,
            comparable_amount=total_amount,
            segments=segments,
            ticketing_type=TicketingType.SINGLE_TICKET,
            travel_duration_minutes=self._duration_from_itineraries(raw_offer),
            booking_link=None,
            risk_flags=(RiskFlag.PROVIDER_UNVERIFIED,),
            provider_quote=quote,
            manual_check_required=False,
        )

    def _segments_from_offer(
        self,
        raw_offer: Mapping[str, Any],
        request: SearchRequest,
    ) -> tuple[Segment, ...]:
        normalized: list[Segment] = []
        itineraries = raw_offer.get("itineraries")
        if not isinstance(itineraries, list):
            return request.segments

        for itinerary in itineraries:
            if not isinstance(itinerary, Mapping):
                continue
            raw_segments = itinerary.get("segments")
            if not isinstance(raw_segments, list):
                continue
            for raw_segment in raw_segments:
                if not isinstance(raw_segment, Mapping):
                    continue
                departure = self._location_data(raw_segment.get("departure"))
                arrival = self._location_data(raw_segment.get("arrival"))
                departing_at = departure.get("at")
                arriving_at = arrival.get("at")
                normalized.append(
                    Segment(
                        origin=str(departure.get("iataCode") or request.origin),
                        destination=str(arrival.get("iataCode") or request.destination),
                        departure_date=(
                            datetime.fromisoformat(str(departing_at)).date()
                            if departing_at
                            else request.departure_date
                        ),
                        departure_time=str(departing_at) if departing_at else None,
                        arrival_time=str(arriving_at) if arriving_at else None,
                        marketing_carrier=(
                            str(raw_segment.get("carrierCode"))
                            if raw_segment.get("carrierCode")
                            else None
                        ),
                        flight_number=(
                            str(raw_segment.get("number"))
                            if raw_segment.get("number")
                            else None
                        ),
                    )
                )
        return tuple(normalized) or request.segments

    def _duration_from_itineraries(self, raw_offer: Mapping[str, Any]) -> int | None:
        itineraries = raw_offer.get("itineraries")
        if not isinstance(itineraries, list):
            return None
        total = 0
        found = False
        for itinerary in itineraries:
            if not isinstance(itinerary, Mapping):
                continue
            duration = self._duration_to_minutes(itinerary.get("duration"))
            if duration is not None:
                total += duration
                found = True
        return total if found else None

    def _location_data(self, value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    def _duration_to_minutes(self, value: Any) -> int | None:
        if not isinstance(value, str):
            return None
        try:
            # Amadeus durations are ISO-8601 values such as PT13H30M or P1DT2H.
            parsed = value.removeprefix("P")
            days = 0
            if "D" in parsed:
                day_part, parsed = parsed.split("D", 1)
                days = int(day_part or 0)
            parsed = parsed.removeprefix("T")
            hours = 0
            minutes = 0
            if "H" in parsed:
                hour_part, parsed = parsed.split("H", 1)
                hours = int(hour_part or 0)
            if "M" in parsed:
                minute_part = parsed.split("M", 1)[0]
                minutes = int(minute_part or 0)
        except ValueError:
            return None
        return int(timedelta(days=days, hours=hours, minutes=minutes).total_seconds() // 60)

    def _travel_class(self, cabin: str) -> str | None:
        classes = {
            "economy": "ECONOMY",
            "premium_economy": "PREMIUM_ECONOMY",
            "business": "BUSINESS",
            "first": "FIRST",
        }
        return classes.get(cabin)

    def _error_message(self, response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return f"Amadeus API error {response.status_code}: {response.text}"
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            first_error = errors[0]
            if isinstance(first_error, Mapping):
                title = first_error.get("title") or "Amadeus API error"
                detail = first_error.get("detail") or first_error.get("message")
                return f"{title}: {detail}" if detail else str(title)
        error_description = body.get("error_description")
        if isinstance(error_description, str) and error_description:
            return error_description
        return f"Amadeus API error {response.status_code}"
