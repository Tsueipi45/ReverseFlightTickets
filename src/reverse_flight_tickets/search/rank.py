"""Offer ranking utilities."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from reverse_flight_tickets.domain import Offer


def rank_offers(offers: Iterable[Offer]) -> tuple[Offer, ...]:
    """Rank priced offers first, then manual checks, with lower risk preferred."""

    def sort_key(offer: Offer) -> tuple[bool, Decimal, int, str]:
        amount = offer.display_amount
        return (
            amount is None,
            amount if amount is not None else Decimal("Infinity"),
            len(offer.risk_flags),
            offer.provider,
        )

    return tuple(sorted(offers, key=sort_key))
