"""Search request expansion for market/currency and future strategies."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from reverse_flight_tickets.domain import SearchRequest, Segment


class SearchVariant(BaseModel):
    model_config = ConfigDict(frozen=True)

    request: SearchRequest
    strategy: str
    source_market: str
    currency: str
    date_shift_days: int = 0
    stopover: str | None = None


def expand_request(request: SearchRequest) -> tuple[SearchVariant, ...]:
    """Create search variants while keeping hidden-city excluded by default."""

    variants: list[SearchVariant] = []
    route_candidates = ((None, request),) + tuple(
        (stopover, _with_stopover_segments(request, stopover)) for stopover in request.stopovers
    )
    for date_shift in range(-request.date_flexibility_days, request.date_flexibility_days + 1):
        for stopover, route_request in route_candidates:
            date_request = route_request.with_date_shift(date_shift)
            for market in request.allowed_markets:
                for currency in request.allowed_currencies:
                    strategy = (
                        "multi_city_stopover"
                        if stopover
                        else (
                            "multi_city_market_currency"
                            if len(route_request.segments) > 2
                            else "market_currency"
                        )
                    )
                    if date_shift:
                        strategy = f"{strategy}_date_flex"
                    variants.append(
                        SearchVariant(
                            request=date_request.with_market_currency(market, currency),
                            strategy=strategy,
                            source_market=market,
                            currency=currency,
                            date_shift_days=date_shift,
                            stopover=stopover,
                        )
                    )
    return tuple(variants)


def _with_stopover_segments(request: SearchRequest, stopover: str) -> SearchRequest:
    outbound: tuple[Segment, ...] = (
        Segment(
            origin=request.origin,
            destination=stopover,
            departure_date=request.departure_date,
        ),
        Segment(
            origin=stopover,
            destination=request.destination,
            departure_date=request.departure_date,
        ),
    )
    if request.return_date is None:
        segments: tuple[Segment, ...] = outbound
    else:
        segments = outbound + (
            Segment(
                origin=request.destination,
                destination=stopover,
                departure_date=request.return_date,
            ),
            Segment(
                origin=stopover,
                destination=request.origin,
                departure_date=request.return_date,
            ),
        )
    return request.model_copy(update={"segments": segments})
