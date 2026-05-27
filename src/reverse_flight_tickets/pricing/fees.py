"""Fee and tax normalization placeholders."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


class FeeBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)

    tax_amount: Decimal = Decimal("0")
    service_fee_amount: Decimal = Decimal("0")
    payment_fee_amount: Decimal = Decimal("0")
    baggage_fee_amount: Decimal = Decimal("0")

    @field_validator(
        "tax_amount",
        "service_fee_amount",
        "payment_fee_amount",
        "baggage_fee_amount",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, value: object) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @property
    def total(self) -> Decimal:
        return (
            self.tax_amount
            + self.service_fee_amount
            + self.payment_fee_amount
            + self.baggage_fee_amount
        )
