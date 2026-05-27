"""Search request expansion for market/currency and future strategies."""

from __future__ import annotations

from dataclasses import dataclass, replace

from reverse_flight_tickets.domain import SearchRequest


@dataclass(frozen=True)
class SearchVariant:
    request: SearchRequest
    strategy: str
    source_market: str
    currency: str


def expand_request(request: SearchRequest) -> tuple[SearchVariant, ...]:
    """Create search variants while keeping hidden-city excluded by default."""

    variants: list[SearchVariant] = []
    for market in request.allowed_markets:
        for currency in request.allowed_currencies:
            variants.append(
                SearchVariant(
                    request=replace(
                        request,
                        allowed_markets=(market,),
                        allowed_currencies=(currency,),
                    ),
                    strategy="market_currency",
                    source_market=market,
                    currency=currency,
                )
            )
    return tuple(variants)
