"""Fee and tax normalization placeholders."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FeeBreakdown:
    tax_amount: Decimal = Decimal("0")
    service_fee_amount: Decimal = Decimal("0")
    payment_fee_amount: Decimal = Decimal("0")
    baggage_fee_amount: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return (
            self.tax_amount
            + self.service_fee_amount
            + self.payment_fee_amount
            + self.baggage_fee_amount
        )
