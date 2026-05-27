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
    date_shift_days: int = 0


def expand_request(request: SearchRequest) -> tuple[SearchVariant, ...]:
    """Create search variants while keeping hidden-city excluded by default."""

    variants: list[SearchVariant] = []
    for date_shift in range(-request.date_flexibility_days, request.date_flexibility_days + 1):
        date_request = request.with_date_shift(date_shift)
        for market in request.allowed_markets:
            for currency in request.allowed_currencies:
                strategy = "multi_city_market_currency" if len(request.segments) > 2 else "market_currency"
                if date_shift:
                    strategy = f"{strategy}_date_flex"
                variants.append(
                    SearchVariant(
                        request=date_request.with_market_currency(market, currency),
                        strategy=strategy,
                        source_market=market,
                        currency=currency,
                        date_shift_days=date_shift,
                    )
                )
    return tuple(variants)
