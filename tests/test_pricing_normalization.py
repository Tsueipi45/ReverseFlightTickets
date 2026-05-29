from decimal import Decimal
from pathlib import Path

import respx
from httpx import Response
import pytest

from reverse_flight_tickets.domain import Offer
from reverse_flight_tickets.pricing import (
    CachedHttpRateConverter,
    StaticRateConverter,
    build_currency_converter,
    convert_currency_amount,
    estimate_fee_breakdown,
)
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


def test_convert_currency_amount_returns_rate_metadata() -> None:
    result = convert_currency_amount(
        Decimal("2225"),
        from_currency="CNY",
        to_currency="USD",
        converter=StaticRateConverter(rates={("CNY", "USD"): Decimal("0.14")}),
    )

    assert result.converted_amount == Decimal("311.50")
    assert result.rate == Decimal("0.140000")
    assert result.to_dict()["from_currency"] == "CNY"


def test_cached_http_rate_converter_uses_cached_rate(tmp_path: Path) -> None:
    cache_path = tmp_path / "rates.json"
    cache_path.write_text(
        """
        {
          "rates": {
            "USD:CNY": {
              "rate": "7.20",
              "fetched_at": "2099-01-01T00:00:00+00:00",
              "provider": "frankfurter",
              "date": "2099-01-01"
            }
          }
        }
        """,
        encoding="utf-8",
    )
    converter = CachedHttpRateConverter(cache_path=cache_path)

    assert converter.convert(Decimal("100"), "USD", "CNY") == Decimal("720.00")


@respx.mock
def test_cached_http_rate_converter_fetches_and_caches_rate(tmp_path: Path) -> None:
    cache_path = tmp_path / "rates.json"
    respx.get("https://api.frankfurter.dev/v2/rate/USD/CNY").mock(
        return_value=Response(200, json={"amount": 1.0, "base": "USD", "target": "CNY", "rate": 7.1})
    )
    converter = CachedHttpRateConverter(cache_path=cache_path)

    assert converter.convert(Decimal("100"), "USD", "CNY") == Decimal("710.00")
    assert '"USD:CNY"' in cache_path.read_text(encoding="utf-8")


def test_build_currency_converter_supports_frankfurter_source(tmp_path: Path) -> None:
    converter = build_currency_converter(
        exchange_rates={},
        exchange_rate_source="frankfurter",
        cache_path=tmp_path / "rates.json",
        cache_ttl_seconds=3600,
        api_base_url="https://api.frankfurter.dev/v2",
        timeout_seconds=5,
    )

    assert isinstance(converter, CachedHttpRateConverter)


def test_cached_http_rate_converter_requires_https_base_url(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        CachedHttpRateConverter(
            cache_path=tmp_path / "rates.json",
            api_base_url="http://localhost:8000",
        )
