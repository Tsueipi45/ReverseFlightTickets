"""Normalized offer models returned by provider connectors."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class FareComponent(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    fee_amount: Decimal | None = None
    currency: str | None = None

    @field_validator("base_amount", "tax_amount", "fee_amount", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Any) -> Decimal | None:
        return _decimal_or_none(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_amount": str(self.base_amount) if self.base_amount is not None else None,
            "tax_amount": str(self.tax_amount) if self.tax_amount is not None else None,
            "fee_amount": str(self.fee_amount) if self.fee_amount is not None else None,
            "currency": self.currency,
        }


class BaggageRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    included_checked_bags: int | None = None
    included_carry_on_bags: int | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "included_checked_bags": self.included_checked_bags,
            "included_carry_on_bags": self.included_carry_on_bags,
            "notes": self.notes,
        }


class ChangeRefundRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    change_allowed: bool | None = None
    refund_allowed: bool | None = None
    penalty_amount: Decimal | None = None
    currency: str | None = None
    notes: str | None = None

    @field_validator("penalty_amount", mode="before")
    @classmethod
    def _coerce_penalty(cls, value: Any) -> Decimal | None:
        return _decimal_or_none(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_allowed": self.change_allowed,
            "refund_allowed": self.refund_allowed,
            "penalty_amount": str(self.penalty_amount) if self.penalty_amount is not None else None,
            "currency": self.currency,
            "notes": self.notes,
        }


class Layover(BaseModel):
    model_config = ConfigDict(frozen=True)

    airport: str
    duration_minutes: int | None = None

    @field_validator("airport", mode="before")
    @classmethod
    def _uppercase_airport(cls, value: Any) -> str:
        return str(value).upper()

    def to_dict(self) -> dict[str, Any]:
        return {
            "airport": self.airport,
            "duration_minutes": self.duration_minutes,
        }


class ProviderQuote(BaseModel):
    """Provider execution metadata kept beside normalized offers."""

    model_config = ConfigDict(frozen=True)

    provider: str
    status: str
    raw: Mapping[str, Any] = Field(default_factory=dict)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
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


class Offer(BaseModel):
    """Canonical provider output consumed by pricing, ranking, booking, and storage."""

    model_config = ConfigDict(frozen=True)

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
    travel_duration_minutes: int | None = None
    layovers: tuple[Layover, ...] = ()
    booking_link: str | None = None
    expires_at: datetime | None = None
    risk_flags: tuple[RiskFlag, ...] = ()
    provider_quote: ProviderQuote | None = None
    manual_check_required: bool = False

    @field_validator("source_market", "currency", mode="before")
    @classmethod
    def _uppercase(cls, value: Any) -> str:
        return str(value).upper()

    @field_validator("total_amount", "comparable_amount", mode="before")
    @classmethod
    def _coerce_amount(cls, value: Any) -> Decimal | None:
        return _decimal_or_none(value)

    @model_validator(mode="after")
    def _sync_manual_flag(self) -> Self:
        if RiskFlag.MANUAL_CHECK_REQUIRED in self.risk_flags and not self.manual_check_required:
            object.__setattr__(self, "manual_check_required", True)
        return self

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
            "travel_duration_minutes": self.travel_duration_minutes,
            "layovers": [layover.to_dict() for layover in self.layovers],
            "booking_link": self.booking_link,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "risk_flags": [flag.value for flag in self.risk_flags],
            "provider_quote": self.provider_quote.to_dict() if self.provider_quote else None,
            "manual_check_required": self.manual_check_required,
        }
