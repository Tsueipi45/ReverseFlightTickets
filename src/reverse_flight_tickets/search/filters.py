"""Local offer filtering utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from reverse_flight_tickets.domain import Offer


@dataclass(frozen=True)
class CarrierFilterResult:
    offers: tuple[Offer, ...]
    filtered_count: int
    excluded_carriers: tuple[str, ...]


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


def carrier_filter_warnings(result: CarrierFilterResult) -> tuple[str, ...]:
    if result.filtered_count == 0:
        return ()
    carriers = ",".join(result.excluded_carriers)
    offer_word = "offer" if result.filtered_count == 1 else "offers"
    return (
        f"filtered {result.filtered_count} {offer_word} by excluded carrier: {carriers}",
    )
