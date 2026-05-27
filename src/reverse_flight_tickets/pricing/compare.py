"""Comparable price calculation hooks."""

from __future__ import annotations

from decimal import Decimal

from reverse_flight_tickets.pricing.currency import CurrencyConverter
from reverse_flight_tickets.pricing.fees import FeeBreakdown


def compute_comparable_amount(
    base_amount: Decimal,
    *,
    source_currency: str,
    target_currency: str,
    converter: CurrencyConverter,
    fees: FeeBreakdown | None = None,
) -> Decimal:
    normalized = converter.convert(base_amount, source_currency, target_currency)
    return normalized + (fees.total if fees else Decimal("0"))
