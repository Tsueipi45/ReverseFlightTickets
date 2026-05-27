"""Concurrent provider orchestration with failure isolation."""

from __future__ import annotations

import asyncio
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from reverse_flight_tickets.domain import Offer, SearchRequest
from reverse_flight_tickets.providers.base import FlightProvider, ProviderContext
from reverse_flight_tickets.search.expansion import SearchVariant, expand_request
from reverse_flight_tickets.search.normalize import normalize_offers
from reverse_flight_tickets.search.rank import rank_offers
from reverse_flight_tickets.search.reverse_strategy import risk_score


class ProviderRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    status: str
    variant: SearchVariant
    offers: tuple[Offer, ...] = ()
    error: str | None = None
    error_type: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "status": self.status,
            "variant": {
                "strategy": self.variant.strategy,
                "source_market": self.variant.source_market,
                "currency": self.variant.currency,
            },
            "offer_count": len(self.offers),
            "error": self.error,
            "error_type": self.error_type,
        }


class SearchRecommendations(BaseModel):
    model_config = ConfigDict(frozen=True)

    lowest_price: Offer | None = None
    lowest_risk: Offer | None = None
    best_value: Offer | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "lowest_price": self.lowest_price.to_dict() if self.lowest_price else None,
            "lowest_risk": self.lowest_risk.to_dict() if self.lowest_risk else None,
            "best_value": self.best_value.to_dict() if self.best_value else None,
        }


class SearchRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    request: SearchRequest
    offers: tuple[Offer, ...]
    provider_runs: tuple[ProviderRun, ...]
    recommendations: SearchRecommendations = Field(default_factory=SearchRecommendations)
    warnings: tuple[str, ...] = Field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "request": self.request.to_dict(),
            "offers": [offer.to_dict() for offer in self.offers],
            "provider_runs": [run.to_dict() for run in self.provider_runs],
            "recommendations": self.recommendations.to_dict(),
            "warnings": list(self.warnings),
        }


class SearchOrchestrator:
    """Expand a request, query providers concurrently, normalize, and rank results."""

    def __init__(
        self,
        providers: Iterable[FlightProvider],
        *,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.providers = tuple(providers)
        self.timeout_seconds = timeout_seconds

    async def search(
        self,
        request: SearchRequest,
        context: ProviderContext | None = None,
    ) -> SearchRunResult:
        variants = expand_request(request)
        tasks = [
            self._query_provider(provider, variant, context)
            for provider in self.providers
            for variant in variants
        ]
        provider_runs = tuple(await asyncio.gather(*tasks)) if tasks else ()
        raw_offers = [offer for run in provider_runs for offer in run.offers]
        normalized = normalize_offers(request, raw_offers)
        deduped = self._deduplicate(normalized)
        ranked = rank_offers(deduped)
        warnings = self._warnings(provider_runs)
        return SearchRunResult(
            request=request,
            offers=ranked,
            provider_runs=provider_runs,
            recommendations=self._recommend(ranked),
            warnings=warnings,
        )

    async def _query_provider(
        self,
        provider: FlightProvider,
        variant: SearchVariant,
        context: ProviderContext | None,
    ) -> ProviderRun:
        timeout = context.timeout_seconds if context else self.timeout_seconds
        try:
            offers = await asyncio.wait_for(
                provider.search(variant.request, context),
                timeout=timeout,
            )
        except Exception as exc:  # Provider failures must not fail the whole search.
            return ProviderRun(
                provider=provider.name,
                status="error",
                variant=variant,
                error=str(exc),
                error_type=type(exc).__name__,
            )
        return ProviderRun(
            provider=provider.name,
            status="ok",
            variant=variant,
            offers=tuple(offers),
        )

    def _warnings(self, provider_runs: tuple[ProviderRun, ...]) -> tuple[str, ...]:
        if not provider_runs:
            return ("no providers configured",)
        if all(run.status == "error" for run in provider_runs):
            return ("all providers failed or are not configured",)
        return ()

    def _deduplicate(self, offers: tuple[Offer, ...]) -> tuple[Offer, ...]:
        seen: set[tuple[object, ...]] = set()
        deduped: list[Offer] = []
        for offer in offers:
            segment_key = tuple(
                (
                    segment.origin,
                    segment.destination,
                    segment.departure_date.isoformat(),
                    segment.marketing_carrier,
                    segment.flight_number,
                )
                for segment in offer.segments
            )
            key = (
                offer.provider,
                offer.source_market,
                offer.currency,
                str(offer.total_amount),
                offer.booking_link,
                segment_key,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(offer)
        return tuple(deduped)

    def _recommend(self, offers: tuple[Offer, ...]) -> SearchRecommendations:
        priced = tuple(offer for offer in offers if offer.display_amount is not None)
        lowest_price = priced[0] if priced else None
        lowest_risk = min(offers, key=lambda offer: (risk_score(offer), offer.display_amount is None)) if offers else None
        best_value = min(
            offers,
            key=lambda offer: (
                offer.display_amount is None,
                risk_score(offer) * 100 + (offer.display_amount or 0),
            ),
        ) if offers else None
        return SearchRecommendations(
            lowest_price=lowest_price,
            lowest_risk=lowest_risk,
            best_value=best_value,
        )
