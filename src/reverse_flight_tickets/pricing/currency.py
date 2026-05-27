"""Currency conversion interfaces."""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field


class CurrencyConverter(Protocol):
    def convert(self, amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
        """Convert a monetary amount to another currency."""


class StaticRateConverter(BaseModel):
    """Simple in-memory converter until an exchange-rate provider is added."""

    model_config = ConfigDict(frozen=True)

    rates: Mapping[tuple[str, str], Decimal] = Field(default_factory=dict)

    def convert(self, amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        if from_currency == to_currency:
            return amount
        rate = self.rates.get((from_currency, to_currency))
        if rate is None:
            raise ValueError(f"missing currency rate: {from_currency}->{to_currency}")
        return (amount * rate).quantize(Decimal("0.01"))
