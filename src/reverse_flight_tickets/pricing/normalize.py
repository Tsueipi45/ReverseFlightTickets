"""Apply comparable pricing to normalized offers."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from reverse_flight_tickets.domain import Offer
from reverse_flight_tickets.pricing.compare import comparable_amount_with_estimated_fees
from reverse_flight_tickets.pricing.currency import CurrencyConverter


def apply_comparable_pricing(
    offers: Iterable[Offer],
    *,
    target_currency: str,
    converter: CurrencyConverter,
    payment_fee_rate: Decimal = Decimal("0"),
    baggage_fee_amount: Decimal = Decimal("0"),
) -> tuple[Offer, ...]:
    priced: list[Offer] = []
    for offer in offers:
        amount = offer.total_amount
        if amount is None:
            priced.append(offer)
            continue
        try:
            comparable_amount = comparable_amount_with_estimated_fees(
                amount,
                source_currency=offer.currency,
                target_currency=target_currency,
                converter=converter,
                payment_fee_rate=payment_fee_rate,
                baggage_fee_amount=baggage_fee_amount,
            )
        except ValueError:
            priced.append(offer)
            continue
        priced.append(
            offer.model_copy(
                update={
                    "comparable_amount": comparable_amount,
                    "currency": target_currency.upper(),
                }
            )
        )
    return tuple(priced)
