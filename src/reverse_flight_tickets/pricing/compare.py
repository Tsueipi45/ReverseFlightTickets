"""Comparable price calculation hooks."""

from __future__ import annotations

from decimal import Decimal

from reverse_flight_tickets.pricing.currency import CurrencyConverter
from reverse_flight_tickets.pricing.fees import FeeBreakdown, estimate_fee_breakdown


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


def comparable_amount_with_estimated_fees(
    base_amount: Decimal,
    *,
    source_currency: str,
    target_currency: str,
    converter: CurrencyConverter,
    payment_fee_rate: Decimal = Decimal("0"),
    baggage_fee_amount: Decimal = Decimal("0"),
) -> Decimal:
    normalized = converter.convert(base_amount, source_currency, target_currency)
    fees = estimate_fee_breakdown(
        normalized,
        payment_fee_rate=payment_fee_rate,
        baggage_fee_amount=baggage_fee_amount,
    )
    return normalized + fees.total
