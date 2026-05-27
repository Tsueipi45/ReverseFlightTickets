"""Normalized offer models returned by provider connectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping

from reverse_flight_tickets.domain.itinerary import Segment
from reverse_flight_tickets.domain.risk import RiskFlag


def _decimal_or_none(value: Decimal | int | float | str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


class TicketingType(StrEnum):
    UNKNOWN = "unknown"
    SINGLE_TICKET = "single_ticket"
    SPLIT_TICKET = "split_ticket"
    SELF_TRANSFER = "self_transfer"
    MANUAL_CHECK = "manual_check"


@dataclass(frozen=True)
class FareComponent:
    base_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    fee_amount: Decimal | None = None
    currency: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_amount": str(self.base_amount) if self.base_amount is not None else None,
            "tax_amount": str(self.tax_amount) if self.tax_amount is not None else None,
            "fee_amount": str(self.fee_amount) if self.fee_amount is not None else None,
            "currency": self.currency,
        }


@dataclass(frozen=True)
class BaggageRule:
    included_checked_bags: int | None = None
    included_carry_on_bags: int | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "included_checked_bags": self.included_checked_bags,
            "included_carry_on_bags": self.included_carry_on_bags,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ChangeRefundRule:
    change_allowed: bool | None = None
    refund_allowed: bool | None = None
    penalty_amount: Decimal | None = None
    currency: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_allowed": self.change_allowed,
            "refund_allowed": self.refund_allowed,
            "penalty_amount": str(self.penalty_amount) if self.penalty_amount is not None else None,
            "currency": self.currency,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ProviderQuote:
    """Provider execution metadata kept beside normalized offers."""

    provider: str
    status: str
    raw: Mapping[str, Any] = field(default_factory=dict)
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "raw": dict(self.raw),
            "requested_at": self.requested_at.isoformat(),
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass(frozen=True)
class Offer:
    """Canonical provider output consumed by pricing, ranking, booking, and storage."""

    provider: str
    source_market: str
    currency: str
    total_amount: Decimal | None = None
    comparable_amount: Decimal | None = None
    segments: tuple[Segment, ...] = ()
    ticketing_type: TicketingType = TicketingType.UNKNOWN
    fare_components: tuple[FareComponent, ...] = ()
    baggage: tuple[BaggageRule, ...] = ()
    fare_rules: tuple[ChangeRefundRule, ...] = ()
    booking_link: str | None = None
    expires_at: datetime | None = None
    risk_flags: tuple[RiskFlag, ...] = ()
    provider_quote: ProviderQuote | None = None
    manual_check_required: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_market", self.source_market.upper())
        object.__setattr__(self, "currency", self.currency.upper())
        object.__setattr__(self, "total_amount", _decimal_or_none(self.total_amount))
        object.__setattr__(self, "comparable_amount", _decimal_or_none(self.comparable_amount))

    @property
    def display_amount(self) -> Decimal | None:
        return self.comparable_amount if self.comparable_amount is not None else self.total_amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "source_market": self.source_market,
            "currency": self.currency,
            "total_amount": str(self.total_amount) if self.total_amount is not None else None,
            "comparable_amount": (
                str(self.comparable_amount) if self.comparable_amount is not None else None
            ),
            "segments": [segment.to_dict() for segment in self.segments],
            "ticketing_type": self.ticketing_type.value,
            "fare_components": [component.to_dict() for component in self.fare_components],
            "baggage": [rule.to_dict() for rule in self.baggage],
            "fare_rules": [rule.to_dict() for rule in self.fare_rules],
            "booking_link": self.booking_link,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "risk_flags": [flag.value for flag in self.risk_flags],
            "provider_quote": self.provider_quote.to_dict() if self.provider_quote else None,
            "manual_check_required": self.manual_check_required,
        }
