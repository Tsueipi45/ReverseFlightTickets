"""Watchlist models for repeated price searches."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from reverse_flight_tickets.domain import SearchRequest


class WatchlistItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    request: SearchRequest
    target_amount: Decimal | None = None
    target_currency: str | None = None
    item_id: str = Field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "request": self.request.to_dict(),
            "target_amount": str(self.target_amount) if self.target_amount is not None else None,
            "target_currency": self.target_currency,
        }
