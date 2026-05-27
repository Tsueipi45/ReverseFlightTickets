"""Price trend summaries from stored search snapshots."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from reverse_flight_tickets.storage.models import SearchSnapshot


class TrendPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    captured_at: datetime
    lowest_amount: Decimal
    currency: str
    provider: str

    def to_dict(self) -> dict[str, str]:
        return {
            "captured_at": self.captured_at.isoformat(),
            "lowest_amount": str(self.lowest_amount),
            "currency": self.currency,
            "provider": self.provider,
        }


class PriceTrendReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    points: tuple[TrendPoint, ...]

    @property
    def latest(self) -> TrendPoint | None:
        return self.points[-1] if self.points else None

    @property
    def lowest(self) -> TrendPoint | None:
        if not self.points:
            return None
        return min(self.points, key=lambda point: point.lowest_amount)

    @property
    def change_from_previous(self) -> Decimal | None:
        if len(self.points) < 2:
            return None
        return self.points[-1].lowest_amount - self.points[-2].lowest_amount

    def to_dict(self) -> dict[str, object]:
        return {
            "points": [point.to_dict() for point in self.points],
            "latest": self.latest.to_dict() if self.latest else None,
            "lowest": self.lowest.to_dict() if self.lowest else None,
            "change_from_previous": (
                str(self.change_from_previous)
                if self.change_from_previous is not None
                else None
            ),
        }


def build_price_trend_report(snapshots: tuple[SearchSnapshot, ...]) -> PriceTrendReport:
    points: list[TrendPoint] = []
    for snapshot in sorted(snapshots, key=lambda item: item.captured_at):
        priced_offers = [
            offer_snapshot.offer
            for offer_snapshot in snapshot.offers
            if offer_snapshot.offer.display_amount is not None
        ]
        if not priced_offers:
            continue
        lowest = min(priced_offers, key=lambda offer: offer.display_amount or Decimal("Infinity"))
        amount = lowest.display_amount
        if amount is None:
            continue
        points.append(
            TrendPoint(
                captured_at=snapshot.captured_at,
                lowest_amount=amount,
                currency=lowest.currency,
                provider=lowest.provider,
            )
        )
    return PriceTrendReport(points=tuple(points))
