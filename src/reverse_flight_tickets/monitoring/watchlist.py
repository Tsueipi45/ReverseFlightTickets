"""Watchlist models for repeated price searches."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import uuid4

from reverse_flight_tickets.domain import SearchRequest


@dataclass(frozen=True)
class WatchlistItem:
    request: SearchRequest
    target_amount: Decimal | None = None
    target_currency: str | None = None
    item_id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "request": self.request.to_dict(),
            "target_amount": str(self.target_amount) if self.target_amount is not None else None,
            "target_currency": self.target_currency,
        }
