"""Currency conversion interfaces."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field


class CurrencyConverter(Protocol):
    def convert(self, amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
        """Convert a monetary amount to another currency."""


class StaticRateConverter(BaseModel):
    """Simple in-memory converter for deterministic local rates."""

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


class CachedHttpRateConverter:
    """HTTP-backed converter with a static-rate override and local JSON cache."""

    def __init__(
        self,
        *,
        static_rates: Mapping[tuple[str, str], Decimal] | None = None,
        cache_path: Path | str = Path("data/exchange_rates_cache.json"),
        cache_ttl_seconds: int = 86_400,
        api_base_url: str = "https://api.frankfurter.dev/v2",
        timeout_seconds: float = 5.0,
    ) -> None:
        self.static_rates = dict(static_rates or {})
        self.cache_path = Path(cache_path)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.api_base_url = _validate_https_base_url(api_base_url).rstrip("/")
        self.timeout_seconds = timeout_seconds

    def convert(self, amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        if from_currency == to_currency:
            return amount
        rate = self.static_rates.get((from_currency, to_currency))
        if rate is None:
            rate = self._cached_rate(from_currency, to_currency)
        if rate is None:
            rate = self._fetch_rate(from_currency, to_currency)
        return (amount * rate).quantize(Decimal("0.01"))

    def _cached_rate(self, from_currency: str, to_currency: str) -> Decimal | None:
        if self.cache_ttl_seconds <= 0:
            return None
        cache = self._load_cache()
        rates = cache.get("rates")
        if not isinstance(rates, dict):
            return None
        entry = rates.get(_pair_key(from_currency, to_currency))
        if not isinstance(entry, dict):
            return None
        fetched_at = _datetime_from_json(entry.get("fetched_at"))
        rate = _decimal_from_json(entry.get("rate"))
        if fetched_at is None or rate is None:
            return None
        if datetime.now(timezone.utc) - fetched_at > timedelta(seconds=self.cache_ttl_seconds):
            return None
        return rate

    def _fetch_rate(self, from_currency: str, to_currency: str) -> Decimal:
        url = f"{self.api_base_url}/rate/{from_currency}/{to_currency}"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(url)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"failed to fetch currency rate: {from_currency}->{to_currency}"
            ) from exc

        if not isinstance(payload, dict):
            raise ValueError(f"invalid currency rate payload: {from_currency}->{to_currency}")
        rate = _decimal_from_json(payload.get("rate"))
        if rate is None:
            raise ValueError(f"missing currency rate: {from_currency}->{to_currency}")
        rate_date = payload.get("date") if isinstance(payload.get("date"), str) else None
        self._save_rate(from_currency, to_currency, rate, rate_date)
        return rate

    def _load_cache(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_rate(
        self,
        from_currency: str,
        to_currency: str,
        rate: Decimal,
        rate_date: str | None,
    ) -> None:
        cache = self._load_cache()
        rates = cache.get("rates")
        if not isinstance(rates, dict):
            rates = {}
            cache["rates"] = rates
        rates[_pair_key(from_currency, to_currency)] = {
            "rate": str(rate),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "provider": "frankfurter",
            "date": rate_date,
        }
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            return


def build_currency_converter(
    *,
    exchange_rates: Mapping[tuple[str, str], Decimal],
    exchange_rate_source: str,
    cache_path: Path | str,
    cache_ttl_seconds: int,
    api_base_url: str,
    timeout_seconds: float,
) -> CurrencyConverter:
    source = exchange_rate_source.strip().lower()
    if source in ("", "static"):
        return StaticRateConverter(rates=exchange_rates)
    if source == "frankfurter":
        return CachedHttpRateConverter(
            static_rates=exchange_rates,
            cache_path=cache_path,
            cache_ttl_seconds=cache_ttl_seconds,
            api_base_url=api_base_url,
            timeout_seconds=timeout_seconds,
        )
    raise ValueError(f"unsupported exchange rate source: {exchange_rate_source}")


def _pair_key(from_currency: str, to_currency: str) -> str:
    return f"{from_currency.upper()}:{to_currency.upper()}"


def _validate_https_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("exchange rate API base URL must be HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("exchange rate API base URL must not include credentials")
    return value


def _decimal_from_json(value: object) -> Decimal | None:
    if not isinstance(value, str | int | float):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _datetime_from_json(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
