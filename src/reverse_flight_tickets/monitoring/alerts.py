"""Price alert evaluation hooks."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from reverse_flight_tickets.domain import Offer


@dataclass(frozen=True)
class PriceDropAlert:
    provider: str
    amount: Decimal
    currency: str
    threshold_amount: Decimal

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "amount": str(self.amount),
            "currency": self.currency,
            "threshold_amount": str(self.threshold_amount),
        }


def evaluate_price_drop(offer: Offer, threshold_amount: Decimal) -> PriceDropAlert | None:
    amount = offer.display_amount
    if amount is None or amount > threshold_amount:
        return None
    return PriceDropAlert(
        provider=offer.provider,
        amount=amount,
        currency=offer.currency,
        threshold_amount=threshold_amount,
    )
