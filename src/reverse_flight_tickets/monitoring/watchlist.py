"""Watchlist models for repeated price searches."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol
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


class WatchlistRepository(Protocol):
    def add(self, item: WatchlistItem) -> str:
        """Store a watchlist item and return its id."""

    def list(self) -> tuple[WatchlistItem, ...]:
        """Return all watchlist items."""

    def get(self, item_id: str) -> WatchlistItem | None:
        """Return one watchlist item by id."""


class InMemoryWatchlistRepository:
    def __init__(self) -> None:
        self._items: dict[str, WatchlistItem] = {}

    def add(self, item: WatchlistItem) -> str:
        self._items[item.item_id] = item
        return item.item_id

    def list(self) -> tuple[WatchlistItem, ...]:
        return tuple(self._items.values())

    def get(self, item_id: str) -> WatchlistItem | None:
        return self._items.get(item_id)
