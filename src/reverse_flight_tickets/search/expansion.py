"""Search request expansion for market/currency and future strategies."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from reverse_flight_tickets.domain import SearchRequest


class SearchVariant(BaseModel):
    model_config = ConfigDict(frozen=True)

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
                    request=request.with_market_currency(market, currency),
                    strategy="market_currency",
                    source_market=market,
                    currency=currency,
                )
            )
    return tuple(variants)
