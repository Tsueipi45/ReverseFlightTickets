"""Currency conversion interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping, Protocol


class CurrencyConverter(Protocol):
    def convert(self, amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
        """Convert a monetary amount to another currency."""


@dataclass(frozen=True)
class StaticRateConverter:
    """Simple in-memory converter until an exchange-rate provider is added."""

    rates: Mapping[tuple[str, str], Decimal] = field(default_factory=dict)

    def convert(self, amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        if from_currency == to_currency:
            return amount
        rate = self.rates.get((from_currency, to_currency))
        if rate is None:
            raise ValueError(f"missing currency rate: {from_currency}->{to_currency}")
        return (amount * rate).quantize(Decimal("0.01"))
