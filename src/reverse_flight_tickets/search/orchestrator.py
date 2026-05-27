"""Concurrent provider orchestration with failure isolation."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from reverse_flight_tickets.compliance import (
    AuditEvent,
    InMemoryAuditLog,
    ProviderTermsRegistry,
    default_terms_registry,
)
from reverse_flight_tickets.domain import Offer, SearchRequest
from reverse_flight_tickets.pricing import StaticRateConverter
from reverse_flight_tickets.pricing.normalize import apply_comparable_pricing
from reverse_flight_tickets.providers.base import FlightProvider, ProviderContext
from reverse_flight_tickets.search.expansion import SearchVariant, expand_request
from reverse_flight_tickets.search.filters import (
    carrier_filter_warnings,
    filter_offers_by_carrier,
    normalize_carrier_codes,
)
from reverse_flight_tickets.search.normalize import normalize_offers
from reverse_flight_tickets.search.rank import rank_offers
from reverse_flight_tickets.search.reverse_strategy import apply_strategy_policy, risk_score


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
                "date_shift_days": self.variant.date_shift_days,
                "stopover": self.variant.stopover,
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
        excluded_carriers: Iterable[str] = (),
        exchange_rates: dict[tuple[str, str], Decimal] | None = None,
        payment_fee_rate: Decimal = Decimal("0"),
        baggage_fee_amount: Decimal = Decimal("0"),
        terms_registry: ProviderTermsRegistry | None = None,
        audit_log: InMemoryAuditLog | None = None,
    ) -> None:
        self.providers = tuple(providers)
        self.timeout_seconds = timeout_seconds
        self.excluded_carriers = normalize_carrier_codes(excluded_carriers)
        self.exchange_rates = exchange_rates or {}
        self.payment_fee_rate = payment_fee_rate
        self.baggage_fee_amount = baggage_fee_amount
        self.terms_registry = terms_registry or default_terms_registry()
        self.audit_log = audit_log

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
        priced = apply_comparable_pricing(
            normalized,
            target_currency=request.allowed_currencies[0],
            converter=StaticRateConverter(rates=self.exchange_rates),
            payment_fee_rate=self.payment_fee_rate,
            baggage_fee_amount=self.baggage_fee_amount,
        )
        policy_applied = apply_strategy_policy(request, priced)
        deduped = self._deduplicate(policy_applied)
        filtered = filter_offers_by_carrier(deduped, self.excluded_carriers)
        ranked = rank_offers(filtered.offers)
        warnings = self._warnings(provider_runs) + carrier_filter_warnings(filtered)
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
        self._record_provider_audit(provider.name, variant, "started")
        if self._requires_multi_city(variant) and not provider.capabilities.supports_multi_city:
            self._record_provider_audit(provider.name, variant, "skipped")
            return ProviderRun(
                provider=provider.name,
                status="skipped",
                variant=variant,
                error="provider does not support multi-city variants",
                error_type="UnsupportedCapability",
            )
        timeout = context.timeout_seconds if context else self.timeout_seconds
        try:
            offers = await asyncio.wait_for(
                provider.search(variant.request, context),
                timeout=timeout,
            )
        except Exception as exc:  # Provider failures must not fail the whole search.
            self._record_provider_audit(provider.name, variant, "error")
            return ProviderRun(
                provider=provider.name,
                status="error",
                variant=variant,
                error=str(exc),
                error_type=type(exc).__name__,
            )
        self._record_provider_audit(provider.name, variant, "ok")
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

    def _requires_multi_city(self, variant: SearchVariant) -> bool:
        return variant.stopover is not None or len(variant.request.segments) > 2

    def _record_provider_audit(
        self,
        provider: str,
        variant: SearchVariant,
        status: str,
    ) -> None:
        if self.audit_log is None:
            return
        terms = self.terms_registry.get(provider)
        self.audit_log.record(
            AuditEvent(
                event_type="provider_query",
                provider=provider,
                status=status,
                metadata={
                    "strategy": variant.strategy,
                    "access_mode": terms.access_mode if terms else "unknown",
                    "production_verified": (
                        str(terms.production_verified).lower() if terms else "false"
                    ),
                },
            )
        )

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
        lowest_risk = (
            min(offers, key=lambda offer: (risk_score(offer), offer.display_amount is None))
            if offers
            else None
        )
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
