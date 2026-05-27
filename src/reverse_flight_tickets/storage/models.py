"""Persistence models for search and price snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from reverse_flight_tickets.domain import Offer, SearchRequest
from reverse_flight_tickets.search import ProviderRun


class OfferSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    offer: Offer
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, object]:
        return {
            "offer": self.offer.to_dict(),
            "captured_at": self.captured_at.isoformat(),
        }

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "OfferSnapshot":
        captured_at = data.get("captured_at")
        return cls(
            offer=Offer.model_validate(data["offer"]),
            captured_at=(
                datetime.fromisoformat(captured_at)
                if isinstance(captured_at, str)
                else datetime.now(timezone.utc)
            ),
        )


class SearchSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    request: SearchRequest
    offers: tuple[OfferSnapshot, ...]
    provider_runs: tuple[ProviderRun, ...] = ()
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "request": self.request.to_dict(),
            "offers": [offer.to_dict() for offer in self.offers],
            "provider_runs": [run.model_dump(mode="json") for run in self.provider_runs],
            "captured_at": self.captured_at.isoformat(),
        }

    @classmethod
    def from_search_result(cls, result: object) -> "SearchSnapshot":
        from reverse_flight_tickets.search import SearchRunResult

        search_result = SearchRunResult.model_validate(result)
        return cls(
            request=search_result.request,
            offers=tuple(OfferSnapshot(offer=offer) for offer in search_result.offers),
            provider_runs=search_result.provider_runs,
        )

    @classmethod
    def from_serialized(
        cls,
        *,
        snapshot_id: str,
        request: dict[str, Any],
        offers: list[dict[str, Any]],
        provider_runs: list[dict[str, Any]],
        captured_at: datetime,
    ) -> "SearchSnapshot":
        from reverse_flight_tickets.search import ProviderRun

        return cls(
            snapshot_id=snapshot_id,
            request=SearchRequest.model_validate(request),
            offers=tuple(OfferSnapshot.from_mapping(offer) for offer in offers),
            provider_runs=tuple(ProviderRun.model_validate(run) for run in provider_runs),
            captured_at=captured_at,
        )
