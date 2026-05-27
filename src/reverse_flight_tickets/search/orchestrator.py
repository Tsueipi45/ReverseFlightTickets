"""Concurrent provider orchestration with failure isolation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Iterable

from reverse_flight_tickets.domain import Offer, SearchRequest
from reverse_flight_tickets.providers.base import FlightProvider, ProviderContext
from reverse_flight_tickets.search.expansion import SearchVariant, expand_request
from reverse_flight_tickets.search.normalize import normalize_offers
from reverse_flight_tickets.search.rank import rank_offers


@dataclass(frozen=True)
class ProviderRun:
    provider: str
    status: str
    variant: SearchVariant
    offers: tuple[Offer, ...] = ()
    error: str | None = None

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
        }


@dataclass(frozen=True)
class SearchRunResult:
    request: SearchRequest
    offers: tuple[Offer, ...]
    provider_runs: tuple[ProviderRun, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "request": self.request.to_dict(),
            "offers": [offer.to_dict() for offer in self.offers],
            "provider_runs": [run.to_dict() for run in self.provider_runs],
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
        ranked = rank_offers(normalized)
        warnings = self._warnings(provider_runs)
        return SearchRunResult(
            request=request,
            offers=ranked,
            provider_runs=provider_runs,
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
