"""Offer normalization hooks."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from reverse_flight_tickets.domain import Offer, SearchRequest


def normalize_offers(request: SearchRequest, offers: Iterable[Offer]) -> tuple[Offer, ...]:
    """Apply cross-provider defaults before pricing and ranking."""

    normalized: list[Offer] = []
    for offer in offers:
        normalized.append(
            replace(
                offer,
                segments=offer.segments or request.segments,
            )
        )
    return tuple(normalized)
