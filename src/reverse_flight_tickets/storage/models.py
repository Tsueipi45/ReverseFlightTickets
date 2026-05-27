"""Persistence models for search and price snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from reverse_flight_tickets.domain import Offer, SearchRequest


@dataclass(frozen=True)
class OfferSnapshot:
    offer: Offer
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, object]:
        return {
            "offer": self.offer.to_dict(),
            "captured_at": self.captured_at.isoformat(),
        }


@dataclass(frozen=True)
class SearchSnapshot:
    request: SearchRequest
    offers: tuple[OfferSnapshot, ...]
    snapshot_id: str = field(default_factory=lambda: str(uuid4()))
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "request": self.request.to_dict(),
            "offers": [offer.to_dict() for offer in self.offers],
            "captured_at": self.captured_at.isoformat(),
        }
