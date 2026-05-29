"""Import browser-captured flight offers into the canonical search result shape."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, unquote, urlparse

from reverse_flight_tickets.domain import (
    Layover,
    Offer,
    ProviderQuote,
    RiskFlag,
    SearchRequest,
    Segment,
    TicketingType,
)
from reverse_flight_tickets.pricing.currency import CurrencyConverter, StaticRateConverter
from reverse_flight_tickets.pricing.normalize import apply_comparable_pricing
from reverse_flight_tickets.search import ProviderRun, SearchRunResult
from reverse_flight_tickets.search.expansion import SearchVariant
from reverse_flight_tickets.search.orchestrator import SearchOrchestrator
from reverse_flight_tickets.search.rank import rank_offers


class BrowserExportError(ValueError):
    """Raised when a browser export cannot be imported safely."""


def import_browser_export(
    path: Path | str,
    *,
    target_currency: str | None = None,
    currency_converter: CurrencyConverter | None = None,
    payment_fee_rate: Decimal = Decimal("0"),
    baggage_fee_amount: Decimal = Decimal("0"),
    save_snapshot: bool = False,
    db_url: str | None = None,
) -> tuple[SearchRunResult, str | None]:
    """Load a Tampermonkey JSON/CSV export and optionally persist it as a snapshot."""

    payload = _load_export(Path(path))
    return import_browser_export_payload(
        payload,
        target_currency=target_currency,
        currency_converter=currency_converter,
        payment_fee_rate=payment_fee_rate,
        baggage_fee_amount=baggage_fee_amount,
        save_snapshot=save_snapshot,
        db_url=db_url,
    )


def import_browser_export_text(
    content: str,
    *,
    filename: str | None = None,
    target_currency: str | None = None,
    currency_converter: CurrencyConverter | None = None,
    payment_fee_rate: Decimal = Decimal("0"),
    baggage_fee_amount: Decimal = Decimal("0"),
    save_snapshot: bool = False,
    db_url: str | None = None,
) -> tuple[SearchRunResult, str | None]:
    """Load a browser export from pasted/uploaded text content."""

    payload = _load_export_text(content, filename=filename)
    return import_browser_export_payload(
        payload,
        target_currency=target_currency,
        currency_converter=currency_converter,
        payment_fee_rate=payment_fee_rate,
        baggage_fee_amount=baggage_fee_amount,
        save_snapshot=save_snapshot,
        db_url=db_url,
    )


def import_browser_export_payload(
    payload: Mapping[str, Any],
    *,
    target_currency: str | None = None,
    currency_converter: CurrencyConverter | None = None,
    payment_fee_rate: Decimal = Decimal("0"),
    baggage_fee_amount: Decimal = Decimal("0"),
    save_snapshot: bool = False,
    db_url: str | None = None,
) -> tuple[SearchRunResult, str | None]:
    """Import an already parsed browser export payload."""

    request = _request_from_payload(payload)
    offers = tuple(_offer_from_mapping(item, payload=payload, request=request) for item in _offer_rows(payload))
    target = (target_currency or request.allowed_currencies[0]).upper()
    priced = apply_comparable_pricing(
        offers,
        target_currency=target,
        converter=currency_converter or StaticRateConverter(rates={}),
        payment_fee_rate=payment_fee_rate,
        baggage_fee_amount=baggage_fee_amount,
    )
    ranked = rank_offers(_deduplicate(priced))
    provider_runs = _provider_runs(payload, request, ranked)
    result = SearchRunResult(
        request=request,
        offers=ranked,
        provider_runs=provider_runs,
        recommendations=SearchOrchestrator([])._recommend(ranked),
        warnings=_warnings(payload, ranked),
    )

    snapshot_id = None
    if save_snapshot:
        if not db_url:
            raise BrowserExportError("db_url is required when save_snapshot is enabled")
        from reverse_flight_tickets.storage import SearchSnapshot, SqliteSearchRepository

        repository = SqliteSearchRepository(db_url)
        snapshot_id = repository.save_search_snapshot(SearchSnapshot.from_search_result(result))
    return result, snapshot_id


def _load_export(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise BrowserExportError(f"export file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _load_csv(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise BrowserExportError(f"invalid browser export JSON: {exc}") from exc
    if not isinstance(data, Mapping):
        raise BrowserExportError("browser export JSON must be an object")
    payload = dict(data)
    if not isinstance(payload.get("offers"), list):
        raise BrowserExportError("browser export JSON must include an offers list")
    return payload


def _load_export_text(content: str, *, filename: str | None = None) -> dict[str, Any]:
    text = content.lstrip("\ufeff").strip()
    if not text:
        raise BrowserExportError("browser export content is empty")
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".csv" or _looks_like_csv(text):
        return _load_csv_text(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BrowserExportError(f"invalid browser export JSON: {exc}") from exc
    if not isinstance(data, Mapping):
        raise BrowserExportError("browser export JSON must be an object")
    payload = dict(data)
    if not isinstance(payload.get("offers"), list):
        raise BrowserExportError("browser export JSON must include an offers list")
    return payload


def _load_csv(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return _payload_from_csv_rows(rows)


def _load_csv_text(content: str) -> dict[str, Any]:
    rows = list(csv.DictReader(content.splitlines()))
    return _payload_from_csv_rows(rows)


def _payload_from_csv_rows(rows: list[dict[str, str]]) -> dict[str, Any]:
    if not rows:
        raise BrowserExportError("browser export CSV does not include any offers")

    first = rows[0]
    request = {
        "origin": first.get("origin") or "",
        "destination": first.get("destination") or "",
        "departure_date": first.get("departure_date") or "",
        "return_date": first.get("return_date") or None,
        "allowed_markets": ["CN"],
        "allowed_currencies": [first.get("currency") or "CNY"],
    }
    offers: list[dict[str, Any]] = []
    for row in rows:
        offer: dict[str, Any] = {
            key: value for key, value in row.items() if value not in (None, "")
        }
        if "flight_numbers" in offer:
            offer["flight_numbers"] = tuple(str(offer["flight_numbers"]).split())
        if "amount" in offer or "currency" in offer:
            offer["price"] = {
                "amount": offer.get("amount"),
                "currency": offer.get("currency") or "CNY",
            }
        offers.append(offer)
    return {
        "schema_version": first.get("schema_version") or "rft-browser-offers/v1",
        "source": first.get("source") or first.get("provider") or "browser",
        "page_url": first.get("page_url") or None,
        "request": request,
        "offers": offers,
    }


def _looks_like_csv(text: str) -> bool:
    first_line = text.splitlines()[0] if text.splitlines() else ""
    headers = {part.strip() for part in first_line.split(",")}
    return {"origin", "destination", "amount"}.issubset(headers)


def _request_from_payload(payload: Mapping[str, Any]) -> SearchRequest:
    request_data = payload.get("request")
    if not isinstance(request_data, Mapping):
        request_data = {}
    first_offer = _first_offer(payload)
    page_request = _request_from_page_url(payload.get("page_url"))
    data = {
        "origin": request_data.get("origin") or first_offer.get("origin") or page_request.get("origin"),
        "destination": (
            request_data.get("destination")
            or first_offer.get("destination")
            or page_request.get("destination")
        ),
        "departure_date": (
            request_data.get("departure_date")
            or first_offer.get("departure_date")
            or page_request.get("departure_date")
        ),
        "return_date": (
            request_data.get("return_date")
            or first_offer.get("return_date")
            or page_request.get("return_date")
        ),
        "passengers": request_data.get("passengers") or page_request.get("passengers"),
        "passenger_count": (
            request_data.get("passenger_count") or page_request.get("passenger_count") or 1
        ),
        "cabin": request_data.get("cabin") or "economy",
        "allowed_markets": request_data.get("allowed_markets") or ("CN",),
        "allowed_currencies": (
            request_data.get("allowed_currencies")
            or first_offer.get("currency")
            or _nested(first_offer, "price", "currency")
            or "CNY"
        ),
    }
    try:
        return SearchRequest.from_mapping(data)
    except Exception as exc:
        raise BrowserExportError(f"cannot build SearchRequest from browser export: {exc}") from exc


def _request_from_page_url(value: object) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        return {}
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    if "fliggy.com" in parsed.netloc:
        return _fliggy_request_from_query(query)
    if "ctrip.com" in parsed.netloc:
        return _ctrip_request_from_url(parsed.path, query)
    return {}


def _fliggy_request_from_query(query: Mapping[str, list[str]]) -> dict[str, Any]:
    request: dict[str, Any] = {}
    journey = _fliggy_search_journey(_query_value(query, "searchJourney"))
    first_segment = journey[0] if journey else {}
    return_segment = journey[1] if len(journey) > 1 else {}

    request["origin"] = _query_value(query, "depCity") or first_segment.get("depCityCode")
    request["destination"] = _query_value(query, "arrCity") or first_segment.get("arrCityCode")
    request["departure_date"] = _query_value(query, "depDate") or first_segment.get("depDate")
    return_date = (
        _query_value(query, "retDate")
        or _query_value(query, "arrDate")
        or return_segment.get("depDate")
    )
    if return_date:
        request["return_date"] = return_date

    adults = _int_or_default(
        _query_value(query, "adultNum") or _query_value(query, "adultPassengerNum"),
        1,
    )
    children = _int_or_default(
        _query_value(query, "childNum") or _query_value(query, "childPassengerNum"),
        0,
    )
    infants = _int_or_default(_query_value(query, "infantPassengerNum"), 0)
    request["passengers"] = {"adults": adults, "children": children, "infants": infants}
    request["passenger_count"] = adults
    return {key: item for key, item in request.items() if item not in (None, "")}


def _fliggy_search_journey(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    candidates = [value, unquote(value)]
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def _ctrip_request_from_url(path: str, query: Mapping[str, list[str]]) -> dict[str, Any]:
    request: dict[str, Any] = {}
    parts = path.rstrip("/").split("/")
    route = parts[-1] if parts else ""
    route_parts = route.split("-")
    if len(route_parts) >= 3:
        request["origin"] = route_parts[-2].upper()
        request["destination"] = route_parts[-1].upper()
    dates = (_query_value(query, "depdate") or "").split("_")
    if dates and dates[0]:
        request["departure_date"] = dates[0]
    if len(dates) > 1 and dates[1]:
        request["return_date"] = dates[1]
    adults = _int_or_default(_query_value(query, "adult"), 1)
    children = _int_or_default(_query_value(query, "child"), 0)
    infants = _int_or_default(_query_value(query, "infant"), 0)
    request["passengers"] = {"adults": adults, "children": children, "infants": infants}
    request["passenger_count"] = adults
    return {key: item for key, item in request.items() if item not in (None, "")}


def _query_value(query: Mapping[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _int_or_default(value: object, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _first_offer(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    for offer in _offer_rows(payload):
        return offer
    raise BrowserExportError("browser export does not include any offers")


def _offer_rows(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    rows = payload.get("offers")
    if not isinstance(rows, list):
        raise BrowserExportError("browser export must include an offers list")
    return tuple(row for row in rows if isinstance(row, Mapping))


def _offer_from_mapping(
    data: Mapping[str, Any],
    *,
    payload: Mapping[str, Any],
    request: SearchRequest,
) -> Offer:
    amount = _decimal_or_none(data.get("amount") or _nested(data, "price", "amount"))
    currency = str(data.get("currency") or _nested(data, "price", "currency") or "CNY").upper()
    provider = _provider_name(data, payload)
    segment = _segment_from_mapping(data, request=request)
    layovers = _layovers_from_stops(data.get("stops"))
    captured_at = _datetime_or_now(data.get("captured_at") or payload.get("captured_at"))
    link = str(data.get("link") or data.get("booking_link") or payload.get("page_url") or "")

    return Offer(
        provider=provider,
        source_market=str(data.get("source_market") or request.allowed_markets[0]),
        currency=currency,
        total_amount=amount,
        segments=(segment,),
        ticketing_type=_ticketing_type(data.get("stops")),
        layovers=layovers,
        booking_link=link or None,
        risk_flags=(RiskFlag.MANUAL_CHECK_REQUIRED, RiskFlag.PROVIDER_UNVERIFIED),
        provider_quote=ProviderQuote(
            provider=provider,
            status="browser_capture",
            raw={
                "schema_version": payload.get("schema_version"),
                "source": payload.get("source"),
                "page_url": payload.get("page_url"),
                "collection_mode": payload.get("collection_mode"),
                "collection": payload.get("collection"),
                "airline": data.get("airline"),
                "flight_numbers": _flight_numbers(data),
                "stops": data.get("stops"),
                "raw_text": data.get("raw_text"),
            },
            requested_at=captured_at,
        ),
        manual_check_required=True,
    )


def _segment_from_mapping(data: Mapping[str, Any], *, request: SearchRequest) -> Segment:
    flight_numbers = _flight_numbers(data)
    carrier, number = _split_flight_number(flight_numbers[0] if flight_numbers else "")
    airline = str(data.get("airline") or "").strip()
    return Segment(
        origin=str(data.get("origin") or request.origin),
        destination=str(data.get("destination") or request.destination),
        departure_date=_date_or_default(data.get("departure_date"), request.departure_date),
        departure_time=_string_or_none(data.get("departure_time")),
        arrival_time=_string_or_none(data.get("arrival_time")),
        marketing_carrier=carrier or airline or None,
        flight_number=number,
    )


def _provider_name(data: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    source = str(data.get("provider") or data.get("source") or payload.get("source") or "browser")
    source = source.strip().lower().replace("_", "-")
    if source in {"ctrip", "trip", "trip.com"}:
        return "ctrip-browser"
    if source in {"fliggy", "飞猪"}:
        return "fliggy-browser"
    return f"{source}-browser" if not source.endswith("-browser") else source


def _flight_numbers(data: Mapping[str, Any]) -> tuple[str, ...]:
    value = data.get("flight_numbers") or data.get("flight_number") or ()
    if isinstance(value, str):
        return tuple(part.strip().upper() for part in value.replace(",", " ").split() if part.strip())
    if isinstance(value, Iterable):
        return tuple(str(part).strip().upper() for part in value if str(part).strip())
    return ()


def _split_flight_number(value: str) -> tuple[str | None, str | None]:
    value = value.strip().upper().replace(" ", "")
    if not value:
        return None, None
    index = 0
    while index < len(value) and not value[index].isdigit():
        index += 1
    carrier = value[:index] or None
    number = value[index:] or None
    return carrier, number


def _ticketing_type(stops: object) -> TicketingType:
    text = str(stops or "")
    if any(token in text for token in ("中转", "中轉", "转机", "轉機", "Transfer")):
        return TicketingType.MANUAL_CHECK
    return TicketingType.UNKNOWN


def _layovers_from_stops(stops: object) -> tuple[Layover, ...]:
    text = str(stops or "").strip()
    if not text or text.lower() == "direct":
        return ()
    airport = _iata_from_text(text)
    return (Layover(airport=airport or "MANUAL"),)


def _iata_from_text(text: str) -> str | None:
    for part in text.replace("/", " ").replace(",", " ").split():
        token = part.strip().upper()
        if len(token) == 3 and token.isalpha():
            return token
    return None


def _provider_runs(
    payload: Mapping[str, Any],
    request: SearchRequest,
    offers: tuple[Offer, ...],
) -> tuple[ProviderRun, ...]:
    providers = tuple(dict.fromkeys(offer.provider for offer in offers))
    return tuple(
        ProviderRun(
            provider=provider,
            status="imported",
            variant=SearchVariant(
                request=request,
                strategy="browser_capture",
                source_market=request.allowed_markets[0],
                currency=request.allowed_currencies[0],
            ),
            offers=tuple(offer for offer in offers if offer.provider == provider),
        )
        for provider in providers
    )


def _warnings(payload: Mapping[str, Any], offers: tuple[Offer, ...]) -> tuple[str, ...]:
    warnings = [
        "browser import uses only already-rendered visible cards; verify details before booking",
        "browser import is marked manual_check_required and provider_unverified",
    ]
    if not offers:
        warnings.append("browser export contained no importable offers")
    if payload.get("schema_version") != "rft-browser-offers/v1":
        warnings.append("browser export schema version is missing or unexpected")
    return tuple(warnings)


def _deduplicate(offers: tuple[Offer, ...]) -> tuple[Offer, ...]:
    seen: set[tuple[object, ...]] = set()
    deduped: list[Offer] = []
    for offer in offers:
        segment = offer.segments[0] if offer.segments else None
        key = (
            offer.provider,
            str(offer.total_amount),
            offer.currency,
            offer.booking_link,
            segment.marketing_carrier if segment else None,
            segment.flight_number if segment else None,
            segment.departure_time if segment else None,
            segment.arrival_time if segment else None,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(offer)
    return tuple(deduped)


def _decimal_or_none(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise BrowserExportError(f"invalid price amount: {value}") from exc


def _nested(data: Mapping[str, Any], key: str, nested_key: str) -> object:
    value = data.get(key)
    if isinstance(value, Mapping):
        return value.get(nested_key)
    return None


def _date_or_default(value: object, default: date) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value)
    return default


def _datetime_or_now(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _string_or_none(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
