"""Vertical trip planning for the city-level flight comparison MVP."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from collections.abc import Iterable as IterableABC
from typing import Iterable, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from reverse_flight_tickets.domain import Offer, Passenger, SearchRequest, Segment
from reverse_flight_tickets.domain.itinerary import Cabin
from reverse_flight_tickets.pricing import CurrencyConverter, StaticRateConverter
from reverse_flight_tickets.pricing.normalize import apply_comparable_pricing
from reverse_flight_tickets.providers import FlightProvider, ProviderContext
from reverse_flight_tickets.search import ProviderRun, SearchOrchestrator
from reverse_flight_tickets.search.rank import rank_offers
from reverse_flight_tickets.storage import SearchRepository

PlanKind = Literal["flight_only", "rail_flight", "airport_stopover"]
FlightFilter = Literal["all", "direct", "via_city"]
PlanPriceStatus = Literal[
    "priced",
    "needs_exchange_rate",
    "needs_manual_flight_price",
    "no_flights",
]

NANJING_KEY = "NANJING"
SHANGHAI_KEY = "SHANGHAI"
TAIPEI_KEY = "TAIPEI"
BEIJING_KEY = "BEIJING"
GUANGZHOU_KEY = "GUANGZHOU"
SHENZHEN_KEY = "SHENZHEN"
HANGZHOU_KEY = "HANGZHOU"
XIAMEN_KEY = "XIAMEN"
FUZHOU_KEY = "FUZHOU"
CHENGDU_KEY = "CHENGDU"
CHONGQING_KEY = "CHONGQING"
WUHAN_KEY = "WUHAN"
QINGDAO_KEY = "QINGDAO"
XIAN_KEY = "XIAN"
HONG_KONG_KEY = "HONG_KONG"
MACAU_KEY = "MACAU"


@dataclass(frozen=True)
class CityDefinition:
    key: str
    value: str
    label: str
    airports: tuple[str, ...]
    aliases: tuple[str, ...]
    rail_station: str


@dataclass(frozen=True)
class RailEstimate:
    per_person_one_way_amount: Decimal
    duration_minutes: int
    notes: str


def _city_alias_key(value: str) -> str:
    return value.strip().casefold().replace(" ", "").replace("-", "").replace("'", "")


CITY_DEFINITIONS = (
    CityDefinition(
        NANJING_KEY,
        "Nanjing",
        "Nanjing / 南京",
        ("NKG",),
        ("nanjing", "南京", "nkg"),
        "Nanjing South",
    ),
    CityDefinition(
        SHANGHAI_KEY,
        "Shanghai",
        "Shanghai / 上海",
        ("PVG", "SHA"),
        ("shanghai", "上海", "pvg", "sha"),
        "Shanghai airport area",
    ),
    CityDefinition(
        TAIPEI_KEY,
        "Taipei",
        "Taipei / 台北",
        ("TPE", "TSA"),
        ("taipei", "台北", "tpe", "tsa"),
        "Taipei airport area",
    ),
    CityDefinition(
        BEIJING_KEY,
        "Beijing",
        "Beijing / 北京",
        ("PEK", "PKX"),
        ("beijing", "北京", "pek", "pkx"),
        "Beijing railway area",
    ),
    CityDefinition(
        GUANGZHOU_KEY,
        "Guangzhou",
        "Guangzhou / 广州",
        ("CAN",),
        ("guangzhou", "广州", "can"),
        "Guangzhou South",
    ),
    CityDefinition(
        SHENZHEN_KEY,
        "Shenzhen",
        "Shenzhen / 深圳",
        ("SZX",),
        ("shenzhen", "深圳", "szx"),
        "Shenzhen North",
    ),
    CityDefinition(
        HANGZHOU_KEY,
        "Hangzhou",
        "Hangzhou / 杭州",
        ("HGH",),
        ("hangzhou", "杭州", "hgh"),
        "Hangzhou East",
    ),
    CityDefinition(
        XIAMEN_KEY,
        "Xiamen",
        "Xiamen / 厦门",
        ("XMN",),
        ("xiamen", "厦门", "xmn"),
        "Xiamen North",
    ),
    CityDefinition(
        FUZHOU_KEY,
        "Fuzhou",
        "Fuzhou / 福州",
        ("FOC",),
        ("fuzhou", "福州", "foc"),
        "Fuzhou railway area",
    ),
    CityDefinition(
        CHENGDU_KEY,
        "Chengdu",
        "Chengdu / 成都",
        ("TFU", "CTU"),
        ("chengdu", "成都", "tfu", "ctu"),
        "Chengdu railway area",
    ),
    CityDefinition(
        CHONGQING_KEY,
        "Chongqing",
        "Chongqing / 重庆",
        ("CKG",),
        ("chongqing", "重庆", "ckg"),
        "Chongqing railway area",
    ),
    CityDefinition(
        WUHAN_KEY,
        "Wuhan",
        "Wuhan / 武汉",
        ("WUH",),
        ("wuhan", "武汉", "wuh"),
        "Wuhan railway area",
    ),
    CityDefinition(
        QINGDAO_KEY,
        "Qingdao",
        "Qingdao / 青岛",
        ("TAO",),
        ("qingdao", "青岛", "tao"),
        "Qingdao railway area",
    ),
    CityDefinition(
        XIAN_KEY,
        "Xi'an",
        "Xi'an / 西安",
        ("XIY",),
        ("xian", "xi'an", "西安", "xiy"),
        "Xi'an North",
    ),
    CityDefinition(
        HONG_KONG_KEY,
        "Hong Kong",
        "Hong Kong / 中国香港",
        ("HKG",),
        ("hongkong", "hong kong", "香港", "hkg"),
        "Hong Kong West Kowloon",
    ),
    CityDefinition(
        MACAU_KEY,
        "Macau",
        "Macau / 中国澳门",
        ("MFM",),
        ("macau", "macao", "澳门", "mfm"),
        "Macau airport area",
    ),
)

CITY_BY_KEY = {definition.key: definition for definition in CITY_DEFINITIONS}
CITY_AIRPORTS = {definition.key: definition.airports for definition in CITY_DEFINITIONS}
CITY_ALIASES = {
    _city_alias_key(alias): definition.key
    for definition in CITY_DEFINITIONS
    for alias in (definition.value, definition.key, *definition.aliases)
}

RAIL_ESTIMATES: dict[tuple[str, str], RailEstimate] = {
    (NANJING_KEY, SHANGHAI_KEY): RailEstimate(
        per_person_one_way_amount=Decimal("180"),
        duration_minutes=180,
        notes="Static MVP estimate: high-speed rail plus local airport transfer buffer.",
    ),
    (HANGZHOU_KEY, SHANGHAI_KEY): RailEstimate(
        per_person_one_way_amount=Decimal("100"),
        duration_minutes=140,
        notes="Static MVP estimate: high-speed rail plus local airport transfer buffer.",
    ),
    (GUANGZHOU_KEY, SHENZHEN_KEY): RailEstimate(
        per_person_one_way_amount=Decimal("90"),
        duration_minutes=110,
        notes="Static MVP estimate: intercity rail plus local airport transfer buffer.",
    ),
}


class TripPlanRequest(BaseModel):
    """User-level request for city-level planning options."""

    model_config = ConfigDict(frozen=True)

    origin_city: str = "Nanjing"
    destination_city: str = "Taipei"
    departure_date: date
    return_date: date
    passenger_count: int = Field(default=1, ge=1, le=9)
    cabin: Cabin = "economy"
    source_market: str = "CN"
    target_currency: str = "CNY"
    include_shanghai_rail: bool = True
    rail_connection_city: str | None = None
    airport_stopover_city: str | None = None
    flight_filter: FlightFilter = "all"
    flight_stopover_city: str | None = None
    manual_exchange_rates: tuple[str, ...] = ()

    @field_validator(
        "origin_city",
        "destination_city",
        "rail_connection_city",
        "airport_stopover_city",
        "flight_stopover_city",
        mode="before",
    )
    @classmethod
    def _normalize_city_text(cls, value: object, info: ValidationInfo) -> str | None:
        if value in (None, ""):
            if info.field_name in (
                "rail_connection_city",
                "airport_stopover_city",
                "flight_stopover_city",
            ):
                return None
            raise ValueError("city cannot be empty")
        normalized = str(value).strip()
        if not normalized:
            if info.field_name in (
                "rail_connection_city",
                "airport_stopover_city",
                "flight_stopover_city",
            ):
                return None
            raise ValueError("city cannot be empty")
        return normalized

    @field_validator("flight_filter", mode="before")
    @classmethod
    def _normalize_flight_filter(cls, value: object) -> str:
        normalized = str(value or "all").strip().lower()
        if normalized not in ("all", "direct", "via_city"):
            raise ValueError("flight_filter must be all, direct, or via_city")
        return normalized

    @field_validator("source_market", "target_currency", mode="before")
    @classmethod
    def _uppercase_code(cls, value: object) -> str:
        normalized = str(value or "").strip().upper()
        if not normalized:
            raise ValueError("market and currency codes cannot be empty")
        return normalized

    @field_validator("manual_exchange_rates", mode="before")
    @classmethod
    def _normalize_manual_rates(cls, value: object) -> tuple[str, ...]:
        if value in (None, ""):
            return ()
        if isinstance(value, str):
            return tuple(part.strip().upper() for part in value.split(",") if part.strip())
        if isinstance(value, IterableABC):
            return tuple(str(part).strip().upper() for part in value if str(part).strip())
        return (str(value).strip().upper(),)

    @model_validator(mode="after")
    def _validate_supported_route(self) -> Self:
        origin_key = city_key(self.origin_city)
        destination_key = city_key(self.destination_city)
        if origin_key == destination_key:
            raise ValueError("origin_city and destination_city cannot be the same")
        rail_connection_key = city_key(self.rail_connection_city) if self.rail_connection_city else None
        airport_stopover_key = (
            city_key(self.airport_stopover_city) if self.airport_stopover_city else None
        )
        flight_stopover_key = (
            city_key(self.flight_stopover_city) if self.flight_stopover_city else None
        )
        for field_name, connection_key in (
            ("rail_connection_city", rail_connection_key),
            ("airport_stopover_city", airport_stopover_key),
            ("flight_stopover_city", flight_stopover_key),
        ):
            if connection_key is None:
                continue
            if connection_key in (origin_key, destination_key):
                raise ValueError(f"{field_name} cannot match origin_city or destination_city")
        if self.flight_filter == "via_city" and flight_stopover_key is None:
            raise ValueError("flight_stopover_city is required when flight_filter is via_city")
        if self.return_date < self.departure_date:
            raise ValueError("return_date cannot be earlier than departure_date")
        return self

    @classmethod
    def from_mapping(cls, data: object) -> "TripPlanRequest":
        return cls.model_validate(data)

    @property
    def passengers(self) -> Passenger:
        return Passenger(adults=self.passenger_count)

    def to_dict(self) -> dict[str, object]:
        return {
            "origin_city": self.origin_city,
            "destination_city": self.destination_city,
            "departure_date": self.departure_date.isoformat(),
            "return_date": self.return_date.isoformat(),
            "passenger_count": self.passenger_count,
            "cabin": self.cabin,
            "source_market": self.source_market,
            "target_currency": self.target_currency,
            "include_shanghai_rail": self.include_shanghai_rail,
            "rail_connection_city": self.rail_connection_city,
            "airport_stopover_city": self.airport_stopover_city,
            "flight_filter": self.flight_filter,
            "flight_stopover_city": self.flight_stopover_city,
            "manual_exchange_rates": list(self.manual_exchange_rates),
        }


class GroundLeg(BaseModel):
    """A static ground transport estimate used by the vertical MVP."""

    model_config = ConfigDict(frozen=True)

    mode: str
    origin: str
    destination: str
    amount: Decimal
    currency: str
    duration_minutes: int
    notes: str | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def _uppercase_currency(cls, value: object) -> str:
        return str(value).upper()

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "origin": self.origin,
            "destination": self.destination,
            "amount": str(self.amount),
            "currency": self.currency,
            "duration_minutes": self.duration_minutes,
            "notes": self.notes,
        }


class FlightSearchSummary(BaseModel):
    """Compact search trace for each airport-pair query used by a plan option."""

    model_config = ConfigDict(frozen=True)

    request: SearchRequest
    offer_count: int
    provider_runs: tuple[ProviderRun, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "request": self.request.to_dict(),
            "offer_count": self.offer_count,
            "provider_runs": [run.to_dict() for run in self.provider_runs],
            "warnings": list(self.warnings),
        }


class VerificationLink(BaseModel):
    """Manual booking or verification entry surfaced at the plan level."""

    model_config = ConfigDict(frozen=True)

    provider: str
    url: str

    def to_dict(self) -> dict[str, str]:
        return {"provider": self.provider, "url": self.url}


class TripPlanOption(BaseModel):
    """One complete user-facing travel plan, including flight and ground pieces."""

    model_config = ConfigDict(frozen=True)

    option_id: str
    title: str
    kind: PlanKind
    flight_origin_airports: tuple[str, ...]
    flight_destination_airports: tuple[str, ...]
    ground_legs: tuple[GroundLeg, ...] = ()
    flight_offers: tuple[Offer, ...] = ()
    best_flight_offer: Offer | None = None
    flight_amount: Decimal | None = None
    flight_currency: str | None = None
    ground_amount: Decimal = Decimal("0")
    total_amount: Decimal | None = None
    currency: str = "CNY"
    estimated_total_duration_minutes: int | None = None
    price_status: PlanPriceStatus = "no_flights"
    verification_links: tuple[VerificationLink, ...] = ()
    searches: tuple[FlightSearchSummary, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "option_id": self.option_id,
            "title": self.title,
            "kind": self.kind,
            "flight_origin_airports": list(self.flight_origin_airports),
            "flight_destination_airports": list(self.flight_destination_airports),
            "ground_legs": [leg.to_dict() for leg in self.ground_legs],
            "flight_offers": [offer.to_dict() for offer in self.flight_offers],
            "best_flight_offer": (
                self.best_flight_offer.to_dict() if self.best_flight_offer else None
            ),
            "flight_amount": str(self.flight_amount) if self.flight_amount is not None else None,
            "flight_currency": self.flight_currency,
            "ground_amount": str(self.ground_amount),
            "total_amount": str(self.total_amount) if self.total_amount is not None else None,
            "currency": self.currency,
            "estimated_total_duration_minutes": self.estimated_total_duration_minutes,
            "price_status": self.price_status,
            "verification_links": [link.to_dict() for link in self.verification_links],
            "searches": [search.to_dict() for search in self.searches],
            "warnings": list(self.warnings),
        }


class TripPlanResult(BaseModel):
    """Ranked trip planning result for the focused MVP."""

    model_config = ConfigDict(frozen=True)

    request: TripPlanRequest
    options: tuple[TripPlanOption, ...]
    recommended_option: TripPlanOption | None = None
    summary: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "request": self.request.to_dict(),
            "options": [option.to_dict() for option in self.options],
            "recommended_option": (
                self.recommended_option.to_dict() if self.recommended_option else None
            ),
            "summary": self.summary,
            "warnings": list(self.warnings),
        }


class TripPlanner:
    """Plan complete travel options by reusing the existing flight search layer."""

    def __init__(
        self,
        providers: Iterable[FlightProvider],
        *,
        timeout_seconds: float = 20.0,
        excluded_carriers: Iterable[str] = (),
        currency_converter: CurrencyConverter | None = None,
        payment_fee_rate: Decimal = Decimal("0"),
        baggage_fee_amount: Decimal = Decimal("0"),
        repository: SearchRepository | None = None,
        max_offers_per_option: int = 8,
    ) -> None:
        self.providers = tuple(providers)
        self.timeout_seconds = timeout_seconds
        self.excluded_carriers = tuple(excluded_carriers)
        self.currency_converter = currency_converter or StaticRateConverter(rates={})
        self.payment_fee_rate = payment_fee_rate
        self.baggage_fee_amount = baggage_fee_amount
        self.repository = repository
        self.max_offers_per_option = max_offers_per_option

    async def plan(
        self,
        request: TripPlanRequest,
        context: ProviderContext | None = None,
    ) -> TripPlanResult:
        candidates = _plan_candidates(request)
        currency_converter = _converter_with_manual_rates(
            self.currency_converter,
            request.manual_exchange_rates,
        )
        options = tuple(
            await asyncio.gather(
                *(
                    self._build_option(
                        candidate,
                        request,
                        context,
                        currency_converter=currency_converter,
                    )
                    for candidate in candidates
                )
            )
        )
        ranked_options = tuple(sorted(options, key=_option_sort_key))
        recommended = next(
            (option for option in ranked_options if option.total_amount is not None),
            ranked_options[0] if ranked_options else None,
        )
        return TripPlanResult(
            request=request,
            options=ranked_options,
            recommended_option=recommended,
            summary=_summary(ranked_options),
            warnings=_result_warnings(ranked_options),
        )

    async def _build_option(
        self,
        candidate: "_PlanCandidate",
        request: TripPlanRequest,
        context: ProviderContext | None,
        *,
        currency_converter: CurrencyConverter,
    ) -> TripPlanOption:
        search_results = await asyncio.gather(
            *(
                self._run_flight_search(
                    search_request,
                    context,
                    currency_converter=currency_converter,
                )
                for search_request in candidate.flight_requests
            )
        )
        offers = rank_offers(
            _filter_flight_offers(
                request,
                _deduplicate_offers(tuple(offer for result in search_results for offer in result.offers)),
            )
        )
        best_offer = _best_priced_offer(offers, request.target_currency)
        flight_amount, flight_currency = _offer_amount_and_currency(best_offer)
        ground_amount = _ground_total(candidate.ground_legs, request.target_currency)
        total_amount = (
            (flight_amount + ground_amount).quantize(Decimal("0.01"))
            if flight_amount is not None and flight_currency == request.target_currency.upper()
            else None
        )
        warnings = tuple(warning for result in search_results for warning in result.warnings)
        return TripPlanOption(
            option_id=candidate.option_id,
            title=candidate.title,
            kind=candidate.kind,
            flight_origin_airports=candidate.flight_origin_airports,
            flight_destination_airports=candidate.flight_destination_airports,
            ground_legs=candidate.ground_legs,
            flight_offers=offers[: self.max_offers_per_option],
            best_flight_offer=best_offer or (offers[0] if offers else None),
            flight_amount=flight_amount,
            flight_currency=flight_currency,
            ground_amount=ground_amount,
            total_amount=total_amount,
            currency=request.target_currency,
            estimated_total_duration_minutes=_estimated_duration(best_offer, candidate.ground_legs),
            price_status=_price_status(
                offers,
                best_offer,
                target_currency=request.target_currency,
                total_amount=total_amount,
            ),
            verification_links=_verification_links(offers),
            searches=tuple(
                FlightSearchSummary(
                    request=result.request,
                    offer_count=len(result.offers),
                    provider_runs=result.provider_runs,
                    warnings=result.warnings,
                )
                for result in search_results
            ),
            warnings=warnings,
        )

    async def _run_flight_search(
        self,
        request: SearchRequest,
        context: ProviderContext | None,
        *,
        currency_converter: CurrencyConverter,
    ) -> "_PlannerSearchResult":
        orchestrator = SearchOrchestrator(
            self.providers,
            timeout_seconds=self.timeout_seconds,
            excluded_carriers=self.excluded_carriers,
            currency_converter=currency_converter,
            payment_fee_rate=self.payment_fee_rate,
            baggage_fee_amount=self.baggage_fee_amount,
        )
        current = await orchestrator.search(request, context)
        historical = self._historical_offers(request)
        offers = _price_offers(
            tuple(current.offers) + historical,
            target_currency=request.allowed_currencies[0],
            currency_converter=currency_converter,
            payment_fee_rate=self.payment_fee_rate,
            baggage_fee_amount=self.baggage_fee_amount,
        )
        ranked = rank_offers(_deduplicate_offers(offers))
        return _PlannerSearchResult(
            request=request,
            offers=ranked,
            provider_runs=current.provider_runs,
            warnings=current.warnings,
        )

    def _historical_offers(self, request: SearchRequest) -> tuple[Offer, ...]:
        if self.repository is None:
            return ()
        return tuple(
            offer_snapshot.offer
            for snapshot in self.repository.list_route_snapshots(request)
            for offer_snapshot in snapshot.offers
        )


@dataclass(frozen=True)
class _PlanCandidate:
    option_id: str
    title: str
    kind: PlanKind
    flight_origin_airports: tuple[str, ...]
    flight_destination_airports: tuple[str, ...]
    flight_requests: tuple[SearchRequest, ...]
    ground_legs: tuple[GroundLeg, ...] = ()


@dataclass(frozen=True)
class _PlannerSearchResult:
    request: SearchRequest
    offers: tuple[Offer, ...]
    provider_runs: tuple[ProviderRun, ...]
    warnings: tuple[str, ...]


class _PricedOption(Protocol):
    option_id: str
    total_amount: Decimal | None
    estimated_total_duration_minutes: int | None


class _LayeredCurrencyConverter:
    def __init__(
        self,
        primary: CurrencyConverter,
        fallback: CurrencyConverter,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    def convert(self, amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
        try:
            return self.primary.convert(amount, from_currency, to_currency)
        except ValueError:
            return self.fallback.convert(amount, from_currency, to_currency)


def city_key(value: str) -> str:
    key = _city_alias_key(value)
    resolved = CITY_ALIASES.get(key)
    if resolved is None:
        raise ValueError(f"unsupported city for vertical MVP: {value}")
    return resolved


def city_options() -> tuple[dict[str, object], ...]:
    """Return city metadata suitable for UI option lists."""

    return tuple(
        {
            "value": definition.value,
            "label": definition.label,
            "airports": list(definition.airports),
            "keywords": list(definition.aliases),
        }
        for definition in CITY_DEFINITIONS
    )


def rail_connection_options(origin_city: str, destination_city: str) -> tuple[dict[str, object], ...]:
    origin_key = city_key(origin_city)
    destination_key = city_key(destination_city)
    return tuple(
        {
            "value": CITY_BY_KEY[target_key].value,
            "label": CITY_BY_KEY[target_key].label,
            "airports": list(CITY_BY_KEY[target_key].airports),
            "amount": str(estimate.per_person_one_way_amount),
            "duration_minutes": estimate.duration_minutes,
        }
        for source_key, target_key, estimate in _rail_estimate_items()
        if source_key == origin_key and target_key not in (origin_key, destination_key)
    )


def _rail_estimate_items() -> tuple[tuple[str, str, RailEstimate], ...]:
    return tuple((source, target, estimate) for (source, target), estimate in RAIL_ESTIMATES.items())


def _converter_with_manual_rates(
    currency_converter: CurrencyConverter,
    manual_exchange_rates: tuple[str, ...],
) -> CurrencyConverter:
    rates = _parse_manual_exchange_rates(manual_exchange_rates)
    if not rates:
        return currency_converter
    return _LayeredCurrencyConverter(
        primary=currency_converter,
        fallback=StaticRateConverter(rates=rates),
    )


def _parse_manual_exchange_rates(
    values: tuple[str, ...],
) -> dict[tuple[str, str], Decimal]:
    rates: dict[tuple[str, str], Decimal] = {}
    for value in values:
        pair, separator, rate_text = value.partition("=")
        if not separator:
            raise ValueError("manual exchange rates must use FROM:TO=RATE format")
        source, pair_separator, target = pair.partition(":")
        if not pair_separator or not source or not target:
            raise ValueError("manual exchange rates must use FROM:TO=RATE format")
        rate = Decimal(rate_text)
        if rate <= 0:
            raise ValueError("manual exchange rate must be positive")
        rates[(source.upper(), target.upper())] = rate
    return rates


def _plan_candidates(request: TripPlanRequest) -> tuple[_PlanCandidate, ...]:
    origin_key = city_key(request.origin_city)
    destination_key = city_key(request.destination_city)
    origin = CITY_BY_KEY[origin_key]
    destination = CITY_BY_KEY[destination_key]
    direct = _PlanCandidate(
        option_id=f"{_option_slug(origin.value)}-flight",
        title=f"{origin.value} flight to {destination.value}",
        kind="flight_only",
        flight_origin_airports=origin.airports,
        flight_destination_airports=destination.airports,
        flight_requests=_flight_requests(
            request,
            origins=origin.airports,
            destinations=destination.airports,
        ),
    )
    candidates = [direct]
    rail_connection_key = _selected_rail_connection_key(request, origin_key, destination_key)
    if rail_connection_key is not None:
        rail_city = CITY_BY_KEY[rail_connection_key]
        rail_legs = _rail_ground_legs(request, origin_key, rail_connection_key)
        if rail_legs:
            candidates.append(
                _PlanCandidate(
                    option_id=f"{_option_slug(rail_city.value)}-rail-flight",
                    title=(
                        f"{origin.value} rail to {rail_city.value} plus "
                        f"{rail_city.value} flight to {destination.value}"
                    ),
                    kind="rail_flight",
                    flight_origin_airports=rail_city.airports,
                    flight_destination_airports=destination.airports,
                    flight_requests=_flight_requests(
                        request,
                        origins=rail_city.airports,
                        destinations=destination.airports,
                    ),
                    ground_legs=rail_legs,
                )
            )
    if request.airport_stopover_city:
        stopover_key = city_key(request.airport_stopover_city)
        stopover = CITY_BY_KEY[stopover_key]
        candidates.append(
            _PlanCandidate(
                option_id=f"{_option_slug(stopover.value)}-airport-stopover",
                title=(
                    f"{origin.value} to {destination.value} via {stopover.value} airport"
                ),
                kind="airport_stopover",
                flight_origin_airports=origin.airports,
                flight_destination_airports=destination.airports,
                flight_requests=_stopover_flight_requests(
                    request,
                    origins=origin.airports,
                    stopovers=stopover.airports,
                    destinations=destination.airports,
                ),
            )
        )
    return tuple(candidates)


def _selected_rail_connection_key(
    request: TripPlanRequest,
    origin_key: str,
    destination_key: str,
) -> str | None:
    if request.rail_connection_city:
        return city_key(request.rail_connection_city)
    if request.include_shanghai_rail:
        default_key = SHANGHAI_KEY
        if (origin_key, default_key) in RAIL_ESTIMATES and default_key != destination_key:
            return default_key
    return None


def _flight_requests(
    request: TripPlanRequest,
    *,
    origins: tuple[str, ...],
    destinations: tuple[str, ...],
) -> tuple[SearchRequest, ...]:
    stopovers = _flight_filter_stopovers(request)
    return tuple(
        SearchRequest(
            origin=origin,
            destination=destination,
            departure_date=request.departure_date,
            return_date=request.return_date,
            passengers=request.passengers,
            cabin=request.cabin,
            allowed_markets=(request.source_market,),
            allowed_currencies=(request.target_currency,),
            stopovers=stopovers,
            include_hidden_city=False,
        )
        for origin in origins
        for destination in destinations
    )


def _flight_filter_stopovers(request: TripPlanRequest) -> tuple[str, ...]:
    if request.flight_filter != "via_city" or request.flight_stopover_city is None:
        return ()
    return CITY_AIRPORTS[city_key(request.flight_stopover_city)]


def _stopover_flight_requests(
    request: TripPlanRequest,
    *,
    origins: tuple[str, ...],
    stopovers: tuple[str, ...],
    destinations: tuple[str, ...],
) -> tuple[SearchRequest, ...]:
    return tuple(
        SearchRequest(
            origin=origin,
            destination=destination,
            departure_date=request.departure_date,
            return_date=request.return_date,
            segments=(
                Segment(
                    origin=origin,
                    destination=stopover,
                    departure_date=request.departure_date,
                ),
                Segment(
                    origin=stopover,
                    destination=destination,
                    departure_date=request.departure_date,
                ),
                Segment(
                    origin=destination,
                    destination=stopover,
                    departure_date=request.return_date,
                ),
                Segment(
                    origin=stopover,
                    destination=origin,
                    departure_date=request.return_date,
                ),
            ),
            passengers=request.passengers,
            cabin=request.cabin,
            allowed_markets=(request.source_market,),
            allowed_currencies=(request.target_currency,),
            include_hidden_city=False,
        )
        for origin in origins
        for stopover in stopovers
        for destination in destinations
    )


def _rail_ground_legs(
    request: TripPlanRequest,
    origin_key: str,
    rail_connection_key: str,
) -> tuple[GroundLeg, ...]:
    estimate = RAIL_ESTIMATES.get((origin_key, rail_connection_key))
    if estimate is None:
        return ()
    origin = CITY_BY_KEY[origin_key]
    rail_city = CITY_BY_KEY[rail_connection_key]
    amount = estimate.per_person_one_way_amount * request.passenger_count
    return (
        GroundLeg(
            mode="rail",
            origin=origin.rail_station,
            destination=rail_city.rail_station,
            amount=amount,
            currency=request.target_currency,
            duration_minutes=estimate.duration_minutes,
            notes=estimate.notes,
        ),
        GroundLeg(
            mode="rail",
            origin=rail_city.rail_station,
            destination=origin.rail_station,
            amount=amount,
            currency=request.target_currency,
            duration_minutes=estimate.duration_minutes,
            notes=estimate.notes,
        ),
    )


def _option_slug(value: str) -> str:
    return _city_alias_key(value)


def _price_offers(
    offers: tuple[Offer, ...],
    *,
    target_currency: str,
    currency_converter: CurrencyConverter,
    payment_fee_rate: Decimal,
    baggage_fee_amount: Decimal,
) -> tuple[Offer, ...]:
    priced: list[Offer] = []
    for offer in offers:
        if offer.total_amount is None:
            priced.append(offer)
            continue
        if offer.currency.upper() == target_currency.upper() and offer.comparable_amount is not None:
            priced.append(offer)
            continue
        priced.extend(
            apply_comparable_pricing(
                (offer,),
                target_currency=target_currency,
                converter=currency_converter,
                payment_fee_rate=payment_fee_rate,
                baggage_fee_amount=baggage_fee_amount,
            )
        )
    return tuple(priced)


def _filter_flight_offers(
    request: TripPlanRequest,
    offers: tuple[Offer, ...],
) -> tuple[Offer, ...]:
    if request.flight_filter == "all":
        return offers
    if request.flight_filter == "direct":
        return tuple(offer for offer in offers if _is_direct_offer(offer))
    if request.flight_filter == "via_city":
        if request.flight_stopover_city is None:
            return offers
        stopover_airports = set(CITY_AIRPORTS[city_key(request.flight_stopover_city)])
        return tuple(offer for offer in offers if _offer_uses_stopover_airports(offer, stopover_airports))
    return offers


def _is_direct_offer(offer: Offer) -> bool:
    if offer.layovers:
        return False
    segments = tuple(offer.segments)
    if not segments:
        return False
    if len(segments) <= 2:
        return True
    if len(segments) % 2:
        return False
    midpoint = len(segments) // 2
    return midpoint == 1


def _offer_uses_stopover_airports(offer: Offer, stopover_airports: set[str]) -> bool:
    if any(layover.airport.upper() in stopover_airports for layover in offer.layovers):
        return True
    segments = tuple(offer.segments)
    if len(segments) <= 1:
        return False
    endpoints = {
        segments[0].origin.upper(),
        segments[-1].destination.upper(),
    }
    intermediate_airports: set[str] = set()
    for segment in segments:
        for airport in (segment.origin.upper(), segment.destination.upper()):
            if airport not in endpoints:
                intermediate_airports.add(airport)
    return bool(intermediate_airports & stopover_airports)


def _deduplicate_offers(offers: tuple[Offer, ...]) -> tuple[Offer, ...]:
    seen: set[tuple[object, ...]] = set()
    deduped: list[Offer] = []
    for offer in offers:
        segment_key = tuple(
            (
                segment.origin,
                segment.destination,
                segment.departure_date.isoformat(),
                segment.marketing_carrier,
                segment.flight_number,
            )
            for segment in offer.segments
        )
        key = (
            offer.provider,
            offer.source_market,
            offer.currency,
            str(offer.total_amount),
            offer.booking_link,
            segment_key,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(offer)
    return tuple(deduped)


def _best_priced_offer(offers: tuple[Offer, ...], target_currency: str) -> Offer | None:
    target = target_currency.upper()
    for offer in offers:
        if offer.currency.upper() == target and _offer_amount(offer) is not None:
            return offer
    for offer in offers:
        if _offer_amount(offer) is not None:
            return offer
    return None


def _offer_amount(offer: Offer | None) -> Decimal | None:
    if offer is None:
        return None
    return offer.display_amount


def _offer_amount_and_currency(offer: Offer | None) -> tuple[Decimal | None, str | None]:
    if offer is None:
        return None, None
    amount = offer.display_amount
    if amount is None:
        return None, None
    return amount, offer.currency.upper()


def _ground_total(legs: tuple[GroundLeg, ...], target_currency: str) -> Decimal:
    total = Decimal("0")
    for leg in legs:
        if leg.currency.upper() != target_currency.upper():
            continue
        total += leg.amount
    return total.quantize(Decimal("0.01"))


def _estimated_duration(
    best_offer: Offer | None,
    ground_legs: tuple[GroundLeg, ...],
) -> int | None:
    ground_minutes = sum(leg.duration_minutes for leg in ground_legs)
    if best_offer is None or best_offer.travel_duration_minutes is None:
        return ground_minutes or None
    return best_offer.travel_duration_minutes + ground_minutes


def _price_status(
    offers: tuple[Offer, ...],
    best_offer: Offer | None,
    *,
    target_currency: str,
    total_amount: Decimal | None,
) -> PlanPriceStatus:
    if total_amount is not None:
        return "priced"
    if best_offer is not None and _offer_amount(best_offer) is not None:
        if best_offer.currency.upper() != target_currency.upper():
            return "needs_exchange_rate"
        return "needs_manual_flight_price"
    if offers:
        return "needs_manual_flight_price"
    return "no_flights"


def _verification_links(offers: tuple[Offer, ...]) -> tuple[VerificationLink, ...]:
    links: list[VerificationLink] = []
    seen: set[tuple[str, str]] = set()
    for offer in offers:
        if not offer.booking_link:
            continue
        key = (offer.provider, offer.booking_link)
        if key in seen:
            continue
        seen.add(key)
        links.append(VerificationLink(provider=offer.provider, url=offer.booking_link))
    return tuple(links[:8])


def _option_sort_key(option: _PricedOption) -> tuple[bool, Decimal, str, int]:
    return (
        option.total_amount is None,
        option.total_amount if option.total_amount is not None else Decimal("Infinity"),
        option.option_id,
        option.estimated_total_duration_minutes or 10_000_000,
    )


def _summary(options: tuple[TripPlanOption, ...]) -> str:
    direct = _first_option_by_kind(options, "flight_only")
    alternatives = tuple(option for option in options if option.kind != "flight_only")
    if direct is None:
        return "No direct city flight plan was generated."
    if not alternatives:
        return f"Only the {direct.title} plan was generated."
    best_alternative = next(
        (option for option in sorted(alternatives, key=_option_sort_key) if option.total_amount is not None),
        alternatives[0],
    )
    if direct.total_amount is None or best_alternative.total_amount is None:
        if (
            direct.price_status == "needs_exchange_rate"
            or best_alternative.price_status == "needs_exchange_rate"
        ):
            return "Need an exchange rate before comparing the connection plan against direct flights."
        return "Need priced flight offers before deciding whether a connection plan is cheaper."
    delta = (best_alternative.total_amount - direct.total_amount).quantize(Decimal("0.01"))
    if delta < 0:
        return f"{best_alternative.title} is cheaper by {abs(delta)} {direct.currency}."
    if delta > 0:
        return f"{direct.title} is cheaper by {delta} {direct.currency}."
    return "The direct and connection plans have the same estimated total cost."


def _result_warnings(options: tuple[TripPlanOption, ...]) -> tuple[str, ...]:
    warnings: list[str] = []
    if any(option.price_status != "priced" for option in options):
        warnings.append("some plans need imported or API-priced flight offers")
    if any(option.price_status == "needs_exchange_rate" for option in options):
        warnings.append("some flight prices need exchange rates before total plan comparison")
    if any(option.kind == "rail_flight" for option in options):
        warnings.append("rail costs are static MVP estimates, not live rail inventory")
    return tuple(warnings)


def _first_option_by_kind(
    options: tuple[TripPlanOption, ...],
    kind: PlanKind,
) -> TripPlanOption | None:
    for option in options:
        if option.kind == kind:
            return option
    return None
