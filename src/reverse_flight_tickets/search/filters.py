"""Local offer filtering utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from reverse_flight_tickets.domain import Offer, SearchRequest


@dataclass(frozen=True)
class CarrierFilterResult:
    offers: tuple[Offer, ...]
    filtered_count: int
    excluded_carriers: tuple[str, ...]


@dataclass(frozen=True)
class RequestPolicyFilterResult:
    offers: tuple[Offer, ...]
    max_layover_filtered_count: int = 0
    max_layover_hours: int | None = None


def normalize_carrier_codes(carriers: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for carrier in carriers:
        code = carrier.strip().upper()
        if code and code not in normalized:
            normalized.append(code)
    return tuple(normalized)


def filter_offers_by_carrier(
    offers: Iterable[Offer],
    excluded_carriers: Iterable[str],
) -> CarrierFilterResult:
    excluded = normalize_carrier_codes(excluded_carriers)
    offer_tuple = tuple(offers)
    if not excluded:
        return CarrierFilterResult(
            offers=offer_tuple,
            filtered_count=0,
            excluded_carriers=(),
        )

    excluded_set = set(excluded)
    filtered: list[Offer] = []
    filtered_count = 0
    for offer in offer_tuple:
        carriers = {
            segment.marketing_carrier.upper()
            for segment in offer.segments
            if segment.marketing_carrier
        }
        if carriers & excluded_set:
            filtered_count += 1
            continue
        filtered.append(offer)
    return CarrierFilterResult(
        offers=tuple(filtered),
        filtered_count=filtered_count,
        excluded_carriers=excluded,
    )


def filter_offers_by_request_policy(
    offers: Iterable[Offer],
    request: SearchRequest,
) -> RequestPolicyFilterResult:
    offer_tuple = tuple(offers)
    if request.max_layover_hours is None:
        return RequestPolicyFilterResult(offers=offer_tuple)

    max_layover_minutes = request.max_layover_hours * 60
    filtered: list[Offer] = []
    filtered_count = 0
    for offer in offer_tuple:
        known_layover_durations = tuple(
            layover.duration_minutes
            for layover in offer.layovers
            if layover.duration_minutes is not None
        )
        if known_layover_durations and max(known_layover_durations) > max_layover_minutes:
            filtered_count += 1
            continue
        filtered.append(offer)

    return RequestPolicyFilterResult(
        offers=tuple(filtered),
        max_layover_filtered_count=filtered_count,
        max_layover_hours=request.max_layover_hours,
    )


def carrier_filter_warnings(result: CarrierFilterResult) -> tuple[str, ...]:
    if result.filtered_count == 0:
        return ()
    carriers = ",".join(result.excluded_carriers)
    offer_word = "offer" if result.filtered_count == 1 else "offers"
    return (
        f"filtered {result.filtered_count} {offer_word} by excluded carrier: {carriers}",
    )


def request_policy_filter_warnings(result: RequestPolicyFilterResult) -> tuple[str, ...]:
    if result.max_layover_filtered_count == 0 or result.max_layover_hours is None:
        return ()
    offer_word = "offer" if result.max_layover_filtered_count == 1 else "offers"
    return (
        f"filtered {result.max_layover_filtered_count} {offer_word} "
        f"by max layover: {result.max_layover_hours}h",
    )
