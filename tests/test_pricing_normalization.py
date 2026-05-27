from decimal import Decimal

from reverse_flight_tickets.domain import Offer
from reverse_flight_tickets.pricing import StaticRateConverter, estimate_fee_breakdown
from reverse_flight_tickets.pricing.normalize import apply_comparable_pricing


def test_estimate_fee_breakdown_applies_payment_and_baggage_fees() -> None:
    fees = estimate_fee_breakdown(
        Decimal("100.00"),
        payment_fee_rate=Decimal("0.03"),
        baggage_fee_amount=Decimal("25.00"),
    )

    assert fees.payment_fee_amount == Decimal("3.00")
    assert fees.baggage_fee_amount == Decimal("25.00")
    assert fees.total == Decimal("28.00")


def test_apply_comparable_pricing_converts_currency_and_adds_estimated_fees() -> None:
    offer = Offer(
        provider="api",
        source_market="US",
        currency="USD",
        total_amount="100.00",
    )

    priced = apply_comparable_pricing(
        (offer,),
        target_currency="CNY",
        converter=StaticRateConverter(rates={("USD", "CNY"): Decimal("7.20")}),
        payment_fee_rate=Decimal("0.02"),
        baggage_fee_amount=Decimal("30.00"),
    )

    assert priced[0].currency == "CNY"
    assert priced[0].comparable_amount == Decimal("764.40")
