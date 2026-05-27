"""Itinerary and search request models."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Mapping, Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Cabin = Literal["economy", "premium_economy", "business", "first"]


def _parse_date(value: Any, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value)
    raise ValueError(f"{field_name} is required and must be an ISO date")


def _optional_date(value: Any, field_name: str) -> date | None:
    if value in (None, ""):
        return None
    return _parse_date(value, field_name)


def _code(value: str, field_name: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _csv_tuple(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value in (None, ""):
        return default
    if isinstance(value, str):
        return tuple(part.strip().upper() for part in value.split(",") if part.strip())
    return tuple(str(part).strip().upper() for part in value if str(part).strip())


def _parse_cabin(value: Any) -> Cabin:
    cabin = str(value or "economy")
    if cabin not in ("economy", "premium_economy", "business", "first"):
        raise ValueError(f"unsupported cabin: {cabin}")
    return cast(Cabin, cabin)


class Segment(BaseModel):
    """One requested or returned flight segment."""

    model_config = ConfigDict(frozen=True)

    origin: str
    destination: str
    departure_date: date
    departure_time: str | None = None
    arrival_time: str | None = None
    marketing_carrier: str | None = None
    flight_number: str | None = None

    @field_validator("origin", "destination", mode="before")
    @classmethod
    def _normalize_code(cls, value: Any) -> str:
        return _code(str(value), "segment airport code")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Segment":
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "departure_date": self.departure_date.isoformat(),
            "departure_time": self.departure_time,
            "arrival_time": self.arrival_time,
            "marketing_carrier": self.marketing_carrier,
            "flight_number": self.flight_number,
        }


class Passenger(BaseModel):
    """Passenger counts grouped by pricing category."""

    model_config = ConfigDict(frozen=True)

    adults: int = 1
    children: int = 0
    infants: int = 0

    @model_validator(mode="after")
    def _validate_counts(self) -> Self:
        if self.adults < 1:
            raise ValueError("at least one adult passenger is required")
        if self.children < 0 or self.infants < 0:
            raise ValueError("child and infant passenger counts cannot be negative")
        return self

    @property
    def total(self) -> int:
        return self.adults + self.children + self.infants

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Passenger":
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, int]:
        return {
            "adults": self.adults,
            "children": self.children,
            "infants": self.infants,
            "total": self.total,
        }


class SearchRequest(BaseModel):
    """Canonical search input passed from interfaces to provider connectors."""

    model_config = ConfigDict(frozen=True)

    origin: str
    destination: str
    departure_date: date
    return_date: date | None = None
    segments: tuple[Segment, ...] = ()
    passengers: Passenger = Field(default_factory=Passenger)
    cabin: Cabin = "economy"
    allowed_markets: tuple[str, ...] = ("US",)
    allowed_currencies: tuple[str, ...] = ("USD",)
    max_layover_hours: int | None = None
    include_split_ticket: bool = False
    include_self_transfer: bool = False
    include_hidden_city: bool = False

    @field_validator("origin", "destination", mode="before")
    @classmethod
    def _normalize_airport_code(cls, value: Any) -> str:
        return _code(str(value), "airport code")

    @field_validator("cabin", mode="before")
    @classmethod
    def _validate_cabin(cls, value: Any) -> Cabin:
        return _parse_cabin(value)

    @field_validator("allowed_markets", "allowed_currencies", mode="before")
    @classmethod
    def _normalize_tuple(cls, value: Any) -> tuple[str, ...]:
        return _csv_tuple(value, ())

    @model_validator(mode="after")
    def _set_defaults_and_validate(self) -> Self:
        allowed_markets = tuple(market.upper() for market in self.allowed_markets if market)
        allowed_currencies = tuple(
            currency.upper() for currency in self.allowed_currencies if currency
        )
        segments = self.segments
        if not self.segments:
            segments = (
                Segment(
                    origin=self.origin,
                    destination=self.destination,
                    departure_date=self.departure_date,
                ),
            )
        if self.cabin not in ("economy", "premium_economy", "business", "first"):
            raise ValueError(f"unsupported cabin: {self.cabin}")
        if not allowed_markets:
            raise ValueError("at least one allowed market is required")
        if not allowed_currencies:
            raise ValueError("at least one allowed currency is required")
        object.__setattr__(self, "allowed_markets", allowed_markets)
        object.__setattr__(self, "allowed_currencies", allowed_currencies)
        object.__setattr__(self, "segments", segments)
        return self

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        *,
        default_markets: tuple[str, ...] = ("US",),
        default_currencies: tuple[str, ...] = ("USD",),
    ) -> "SearchRequest":
        passenger_data = data.get("passengers")
        if isinstance(passenger_data, Mapping):
            passengers = Passenger.from_mapping(passenger_data)
        else:
            passengers = Passenger(adults=int(data.get("passenger_count", 1)))

        segments_data = data.get("segments") or ()
        segments = tuple(Segment.from_mapping(segment) for segment in segments_data)

        origin = str(data.get("origin") or (segments[0].origin if segments else ""))
        destination = str(data.get("destination") or (segments[-1].destination if segments else ""))
        departure_date = _parse_date(
            data.get("departure_date") or (segments[0].departure_date if segments else None),
            "departure_date",
        )

        return cls(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=_optional_date(data.get("return_date"), "return_date"),
            segments=segments,
            passengers=passengers,
            cabin=_parse_cabin(data.get("cabin", "economy")),
            allowed_markets=_csv_tuple(data.get("allowed_markets"), default_markets),
            allowed_currencies=_csv_tuple(data.get("allowed_currencies"), default_currencies),
            max_layover_hours=(
                None
                if data.get("max_layover_hours") in (None, "")
                else int(data["max_layover_hours"])
            ),
            include_split_ticket=bool(data.get("include_split_ticket", False)),
            include_self_transfer=bool(data.get("include_self_transfer", False)),
            include_hidden_city=bool(data.get("include_hidden_city", False)),
        )

    def with_market_currency(self, market: str, currency: str) -> "SearchRequest":
        return self.model_copy(
            update={
                "allowed_markets": (market.upper(),),
                "allowed_currencies": (currency.upper(),),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "departure_date": self.departure_date.isoformat(),
            "return_date": self.return_date.isoformat() if self.return_date else None,
            "segments": [segment.to_dict() for segment in self.segments],
            "passengers": self.passengers.to_dict(),
            "passenger_count": self.passengers.total,
            "cabin": self.cabin,
            "allowed_markets": list(self.allowed_markets),
            "allowed_currencies": list(self.allowed_currencies),
            "max_layover_hours": self.max_layover_hours,
            "include_split_ticket": self.include_split_ticket,
            "include_self_transfer": self.include_self_transfer,
            "include_hidden_city": self.include_hidden_city,
        }
