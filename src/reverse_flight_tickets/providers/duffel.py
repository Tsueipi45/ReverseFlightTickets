"""Duffel API provider."""

from __future__ import annotations

from datetime import datetime
import re
from time import perf_counter
from typing import Any, Mapping, Sequence

import httpx

from reverse_flight_tickets.domain import (
    BaggageRule,
    ChangeRefundRule,
    FareComponent,
    Layover,
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


DUFFEL_API_BASE_URL = "https://api.duffel.com"
DUFFEL_API_VERSION = "v2"


class DuffelProvider(BaseProvider):
    """Duffel sandbox/production offer request connector."""

    name = "duffel"
    capabilities = ProviderCapability(
        supports_multi_city=True,
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
        token = self._credential(context, "DUFFEL_TOKEN")
        if not token:
            raise ProviderNotConfigured("Duffel requires DUFFEL_API_TOKEN")

        timeout = context.timeout_seconds if context else 20.0
        payload = self._build_offer_request_payload(request)
        started_at = perf_counter()
        async with httpx.AsyncClient(
            base_url=DUFFEL_API_BASE_URL,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Duffel-Version": DUFFEL_API_VERSION,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        ) as client:
            response = await client.post("/air/offer_requests", json=payload)
        latency_ms = int((perf_counter() - started_at) * 1000)

        if response.status_code >= 400:
            raise ProviderError(self._error_message(response))

        body = response.json()
        data = body.get("data", {})
        offers = data.get("offers", [])
        if not isinstance(offers, list):
            raise ProviderError("Duffel response did not include an offers list")

        return tuple(
            self._offer_from_duffel(
                offer,
                request=request,
                latency_ms=latency_ms,
            )
            for offer in offers
            if isinstance(offer, Mapping)
        )

    def _build_offer_request_payload(self, request: SearchRequest) -> dict[str, object]:
        passengers: list[dict[str, str]] = []
        passengers.extend({"type": "adult"} for _ in range(request.passengers.adults))
        passengers.extend({"type": "child"} for _ in range(request.passengers.children))
        passengers.extend({"type": "infant_without_seat"} for _ in range(request.passengers.infants))

        return {
            "data": {
                "slices": [
                    {
                        "origin": segment.origin,
                        "destination": segment.destination,
                        "departure_date": segment.departure_date.isoformat(),
                    }
                    for segment in request.segments
                ],
                "passengers": passengers,
                "cabin_class": self._duffel_cabin(request.cabin),
            }
        }

    def _offer_from_duffel(
        self,
        raw_offer: Mapping[str, Any],
        *,
        request: SearchRequest,
        latency_ms: int,
    ) -> Offer:
        currency = str(raw_offer.get("total_currency") or self._first_currency(request))
        total_amount = raw_offer.get("total_amount")
        base_amount = raw_offer.get("base_amount")
        tax_amount = raw_offer.get("tax_amount")
        segments = self._segments_from_offer(raw_offer, request)
        raw_conditions = raw_offer.get("conditions")
        conditions: Mapping[str, Any] = raw_conditions if isinstance(raw_conditions, Mapping) else {}
        expires_at = self._parse_datetime(raw_offer.get("expires_at"))
        quote = ProviderQuote(
            provider=self.name,
            status="ok",
            raw={
                "id": raw_offer.get("id"),
                "owner": raw_offer.get("owner"),
                "live_mode": raw_offer.get("live_mode"),
                "total_emissions_kg": raw_offer.get("total_emissions_kg"),
            },
            latency_ms=latency_ms,
        )

        risk_flags = self._risk_flags(raw_offer)
        return Offer(
            provider=self.name,
            source_market=self._first_market(request),
            currency=currency,
            total_amount=total_amount,
            comparable_amount=total_amount,
            segments=segments,
            ticketing_type=TicketingType.SINGLE_TICKET,
            fare_components=(
                FareComponent(
                    base_amount=base_amount,
                    tax_amount=tax_amount,
                    currency=currency,
                ),
            ),
            baggage=self._baggage_rules(raw_offer),
            fare_rules=(
                ChangeRefundRule(
                    change_allowed=self._condition_allowed(conditions, "change_before_departure"),
                    refund_allowed=self._condition_allowed(conditions, "refund_before_departure"),
                    currency=currency,
                ),
            ),
            travel_duration_minutes=self._travel_duration_minutes(raw_offer),
            layovers=self._layovers(raw_offer),
            booking_link=None,
            expires_at=expires_at,
            risk_flags=risk_flags,
            provider_quote=quote,
            manual_check_required=False,
        )

    def _segments_from_offer(
        self,
        raw_offer: Mapping[str, Any],
        request: SearchRequest,
    ) -> tuple[Segment, ...]:
        normalized: list[Segment] = []
        slices = raw_offer.get("slices")
        if not isinstance(slices, list):
            return request.segments

        for raw_slice in slices:
            if not isinstance(raw_slice, Mapping):
                continue
            for raw_segment in raw_slice.get("segments", []):
                if not isinstance(raw_segment, Mapping):
                    continue
                origin = self._airport_code(raw_segment.get("origin")) or request.origin
                destination = self._airport_code(raw_segment.get("destination")) or request.destination
                departing_at = str(raw_segment.get("departing_at") or "")
                arriving_at = str(raw_segment.get("arriving_at") or "")
                normalized.append(
                    Segment(
                        origin=origin,
                        destination=destination,
                        departure_date=(
                            datetime.fromisoformat(departing_at.replace("Z", "+00:00")).date()
                            if departing_at
                            else request.departure_date
                        ),
                        departure_time=departing_at or None,
                        arrival_time=arriving_at or None,
                        marketing_carrier=self._carrier_code(raw_segment),
                        flight_number=(
                            str(raw_segment.get("marketing_carrier_flight_number"))
                            if raw_segment.get("marketing_carrier_flight_number")
                            else None
                        ),
                    )
                )
        return tuple(normalized) or request.segments

    def _travel_duration_minutes(self, raw_offer: Mapping[str, Any]) -> int | None:
        slices = raw_offer.get("slices")
        if not isinstance(slices, list):
            return None

        total = 0
        found_duration = False
        for raw_slice in slices:
            if not isinstance(raw_slice, Mapping):
                continue
            duration = self._duration_to_minutes(raw_slice.get("duration"))
            if duration is not None:
                total += duration
                found_duration = True
        return total if found_duration else None

    def _layovers(self, raw_offer: Mapping[str, Any]) -> tuple[Layover, ...]:
        layovers: list[Layover] = []
        slices = raw_offer.get("slices")
        if not isinstance(slices, list):
            return ()

        for raw_slice in slices:
            if not isinstance(raw_slice, Mapping):
                continue
            segments = [
                segment
                for segment in raw_slice.get("segments", [])
                if isinstance(segment, Mapping)
            ]
            for current_segment, next_segment in zip(segments, segments[1:]):
                airport = self._airport_code(current_segment.get("destination"))
                if not airport:
                    continue
                duration_minutes = self._layover_minutes(current_segment, next_segment)
                layovers.append(
                    Layover(
                        airport=airport,
                        duration_minutes=duration_minutes,
                    )
                )
        return tuple(layovers)

    def _baggage_rules(self, raw_offer: Mapping[str, Any]) -> tuple[BaggageRule, ...]:
        checked_bags = 0
        carry_on_bags = 0
        slices = raw_offer.get("slices")
        if not isinstance(slices, list):
            return ()

        for raw_slice in slices:
            if not isinstance(raw_slice, Mapping):
                continue
            for raw_segment in raw_slice.get("segments", []):
                if not isinstance(raw_segment, Mapping):
                    continue
                for passenger in raw_segment.get("passengers", []):
                    if not isinstance(passenger, Mapping):
                        continue
                    baggages = passenger.get("baggages", [])
                    if not isinstance(baggages, list):
                        continue
                    for baggage in baggages:
                        if not isinstance(baggage, Mapping):
                            continue
                        quantity = int(baggage.get("quantity") or 0)
                        baggage_type = baggage.get("type")
                        if baggage_type == "checked":
                            checked_bags = max(checked_bags, quantity)
                        elif baggage_type == "carry_on":
                            carry_on_bags = max(carry_on_bags, quantity)

        if checked_bags == 0 and carry_on_bags == 0:
            return ()
        return (
            BaggageRule(
                included_checked_bags=checked_bags,
                included_carry_on_bags=carry_on_bags,
            ),
        )

    def _risk_flags(self, raw_offer: Mapping[str, Any]) -> tuple[RiskFlag, ...]:
        flags: list[RiskFlag] = []
        if raw_offer.get("live_mode") is False:
            flags.append(RiskFlag.PROVIDER_UNVERIFIED)
        return tuple(flags)

    def _condition_allowed(self, conditions: Mapping[str, Any], key: str) -> bool | None:
        value = conditions.get(key)
        if not isinstance(value, Mapping):
            return None
        allowed = value.get("allowed")
        return allowed if isinstance(allowed, bool) else None

    def _airport_code(self, value: Any) -> str | None:
        if isinstance(value, Mapping):
            iata_code = value.get("iata_code")
            return str(iata_code).upper() if iata_code else None
        return None

    def _carrier_code(self, raw_segment: Mapping[str, Any]) -> str | None:
        carrier = raw_segment.get("marketing_carrier")
        if isinstance(carrier, Mapping):
            iata_code = carrier.get("iata_code")
            return str(iata_code).upper() if iata_code else None
        return None

    def _parse_datetime(self, value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _duration_to_minutes(self, value: Any) -> int | None:
        if not isinstance(value, str):
            return None
        match = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?", value)
        if match is None:
            return None
        days = int(match.group(1) or 0)
        hours = int(match.group(2) or 0)
        minutes = int(match.group(3) or 0)
        return days * 24 * 60 + hours * 60 + minutes

    def _layover_minutes(
        self,
        current_segment: Mapping[str, Any],
        next_segment: Mapping[str, Any],
    ) -> int | None:
        arriving_at = current_segment.get("arriving_at")
        departing_at = next_segment.get("departing_at")
        if not isinstance(arriving_at, str) or not isinstance(departing_at, str):
            return None
        arrival = self._parse_datetime(arriving_at)
        departure = self._parse_datetime(departing_at)
        if arrival is None or departure is None:
            return None
        return max(0, int((departure - arrival).total_seconds() // 60))

    def _duffel_cabin(self, cabin: str) -> str:
        if cabin == "premium_economy":
            return "premium_economy"
        return cabin

    def _error_message(self, response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return f"Duffel API error {response.status_code}: {response.text}"
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            first_error = errors[0]
            if isinstance(first_error, Mapping):
                title = first_error.get("title") or "Duffel API error"
                message = first_error.get("message") or first_error.get("detail")
                return f"{title}: {message}" if message else str(title)
        return f"Duffel API error {response.status_code}"
