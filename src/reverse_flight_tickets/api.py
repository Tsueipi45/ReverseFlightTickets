"""FastAPI REST service and local Web UI."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from reverse_flight_tickets import __version__
from reverse_flight_tickets.config import AppConfig
from reverse_flight_tickets.domain import Offer, SearchRequest
from reverse_flight_tickets.importers import BrowserExportError, import_browser_export_text
from reverse_flight_tickets.providers import (
    ProviderContext,
    available_provider_metadata,
    providers_from_names,
)
from reverse_flight_tickets.pricing import (
    CurrencyConverter,
    build_currency_converter,
    convert_currency_amount,
)
from reverse_flight_tickets.pricing.normalize import apply_comparable_pricing
from reverse_flight_tickets.search import SearchOrchestrator
from reverse_flight_tickets.search.filters import normalize_carrier_codes
from reverse_flight_tickets.search.rank import rank_offers
from reverse_flight_tickets.storage import SearchSnapshot, SqliteSearchRepository
from reverse_flight_tickets.trip_planner import (
    TripPlanRequest,
    TripPlanner,
    city_options,
    rail_connection_options,
)

DEFAULT_EXCLUDED_CARRIERS = ("ZZ",)


class SearchApiRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    origin: str
    destination: str
    departure_date: str
    return_date: str | None = None
    passenger_count: int = Field(default=1, ge=1)
    cabin: str = "economy"
    allowed_markets: tuple[str, ...] = ("US",)
    allowed_currencies: tuple[str, ...] = ("USD",)
    stopovers: tuple[str, ...] = ()
    date_flexibility_days: int = Field(default=0, ge=0)
    max_layover_hours: int | None = Field(default=None, ge=0)
    include_split_ticket: bool = False
    include_self_transfer: bool = False
    include_hidden_city: bool = False
    provider_names: tuple[str, ...] = ()
    include_research: bool = False
    exclude_carriers: tuple[str, ...] = ()
    include_test_carriers: bool = False
    save_snapshot: bool = False


class BrowserImportApiRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str = Field(min_length=1)
    filename: str | None = None
    target_currency: str | None = None
    save_snapshot: bool = False


class CurrencyConvertApiRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: Decimal
    from_currency: str
    to_currency: str


class TripPlanApiRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    origin_city: str = "Nanjing"
    destination_city: str = "Taipei"
    departure_date: str
    return_date: str
    passenger_count: int = Field(default=1, ge=1)
    cabin: str = "economy"
    source_market: str = "CN"
    target_currency: str = "CNY"
    include_shanghai_rail: bool = True
    rail_connection_city: str | None = None
    airport_stopover_city: str | None = None
    flight_filter: str = "all"
    flight_stopover_city: str | None = None
    manual_exchange_rates: tuple[str, ...] = ()
    provider_names: tuple[str, ...] = ()
    include_test_carriers: bool = False


app = FastAPI(
    title="ReverseFlightTickets API",
    version=__version__,
)


@app.get("/", response_class=HTMLResponse)
async def web_ui() -> str:
    return WEB_UI_HTML


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/providers")
async def providers() -> dict[str, object]:
    return {"providers": list(available_provider_metadata())}


@app.get("/api/trip-plan/metadata")
async def trip_plan_metadata(
    origin_city: str = "Nanjing",
    destination_city: str = "Taipei",
) -> dict[str, object]:
    try:
        rail_options = rail_connection_options(origin_city, destination_city)
    except ValueError:
        rail_options = ()
    return {
        "cities": list(city_options()),
        "rail_connection_options": list(rail_options),
        "markets": [
            {"value": "CN", "label": "中国大陆", "meta": "Mainland China point of sale"},
            {"value": "HK", "label": "中国香港", "meta": "Hong Kong point of sale"},
            {"value": "MO", "label": "中国澳门", "meta": "Macau point of sale"},
            {"value": "TW", "label": "中国台湾", "meta": "Taiwan point of sale"},
            {"value": "US", "label": "美国", "meta": "United States point of sale"},
            {"value": "JP", "label": "日本", "meta": "Japan point of sale"},
            {"value": "SG", "label": "新加坡", "meta": "Singapore point of sale"},
        ],
        "currencies": [
            {"value": "CNY", "label": "CNY", "meta": "Chinese yuan"},
            {"value": "USD", "label": "USD", "meta": "US dollar"},
            {"value": "TWD", "label": "TWD", "meta": "New Taiwan dollar"},
            {"value": "HKD", "label": "HKD", "meta": "Hong Kong dollar"},
            {"value": "MOP", "label": "MOP", "meta": "Macau pataca"},
            {"value": "JPY", "label": "JPY", "meta": "Japanese yen"},
            {"value": "SGD", "label": "SGD", "meta": "Singapore dollar"},
        ],
    }


@app.post("/api/search")
async def search(payload: SearchApiRequest) -> dict[str, object]:
    config = AppConfig.from_env()
    request = _search_request(payload, config)
    try:
        providers_to_query = providers_from_names(
            payload.provider_names,
            include_research=payload.include_research,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    context = ProviderContext(
        credentials=config.provider_secret_map(),
        timeout_seconds=config.provider_timeout_seconds,
    )
    currency_converter = build_currency_converter(
        exchange_rates=config.exchange_rates,
        exchange_rate_source=config.exchange_rate_source,
        cache_path=config.exchange_rate_cache_path,
        cache_ttl_seconds=config.exchange_rate_cache_ttl_seconds,
        api_base_url=config.exchange_rate_api_base_url,
        timeout_seconds=config.exchange_rate_timeout_seconds,
    )
    orchestrator = SearchOrchestrator(
        providers_to_query,
        timeout_seconds=config.provider_timeout_seconds,
        excluded_carriers=_excluded_carriers(payload),
        currency_converter=currency_converter,
        payment_fee_rate=config.payment_fee_rate,
        baggage_fee_amount=config.baggage_fee_amount,
    )
    result = await orchestrator.search(request, context)
    snapshot_id: str | None = None
    repository = SqliteSearchRepository(config.database_url)
    if payload.save_snapshot:
        snapshot_id = repository.save_search_snapshot(SearchSnapshot.from_search_result(result))

    response = result.to_dict()
    response["snapshot_id"] = snapshot_id
    response.update(
        _aggregate_response(
            repository,
            request,
            tuple(result.offers),
            currency_converter=currency_converter,
            payment_fee_rate=config.payment_fee_rate,
            baggage_fee_amount=config.baggage_fee_amount,
        )
    )
    return response


@app.post("/api/import-browser")
async def import_browser(payload: BrowserImportApiRequest) -> dict[str, object]:
    config = AppConfig.from_env()
    try:
        result, snapshot_id = import_browser_export_text(
            payload.content,
            filename=payload.filename,
            target_currency=payload.target_currency,
            currency_converter=build_currency_converter(
                exchange_rates=config.exchange_rates,
                exchange_rate_source=config.exchange_rate_source,
                cache_path=config.exchange_rate_cache_path,
                cache_ttl_seconds=config.exchange_rate_cache_ttl_seconds,
                api_base_url=config.exchange_rate_api_base_url,
                timeout_seconds=config.exchange_rate_timeout_seconds,
            ),
            payment_fee_rate=config.payment_fee_rate,
            baggage_fee_amount=config.baggage_fee_amount,
            save_snapshot=payload.save_snapshot,
            db_url=config.database_url,
        )
    except BrowserExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = result.to_dict()
    response["snapshot_id"] = snapshot_id
    repository = SqliteSearchRepository(config.database_url)
    currency_converter = build_currency_converter(
        exchange_rates=config.exchange_rates,
        exchange_rate_source=config.exchange_rate_source,
        cache_path=config.exchange_rate_cache_path,
        cache_ttl_seconds=config.exchange_rate_cache_ttl_seconds,
        api_base_url=config.exchange_rate_api_base_url,
        timeout_seconds=config.exchange_rate_timeout_seconds,
    )
    response.update(
        _aggregate_response(
            repository,
            result.request,
            tuple(result.offers),
            currency_converter=currency_converter,
            payment_fee_rate=config.payment_fee_rate,
            baggage_fee_amount=config.baggage_fee_amount,
        )
    )
    return response


@app.post("/api/currency/convert")
async def convert_currency(payload: CurrencyConvertApiRequest) -> dict[str, object]:
    config = AppConfig.from_env()
    try:
        result = convert_currency_amount(
            payload.amount,
            from_currency=payload.from_currency,
            to_currency=payload.to_currency,
            converter=build_currency_converter(
                exchange_rates=config.exchange_rates,
                exchange_rate_source=config.exchange_rate_source,
                cache_path=config.exchange_rate_cache_path,
                cache_ttl_seconds=config.exchange_rate_cache_ttl_seconds,
                api_base_url=config.exchange_rate_api_base_url,
                timeout_seconds=config.exchange_rate_timeout_seconds,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dict(result.to_dict())


@app.post("/api/trip-plan")
async def trip_plan(payload: TripPlanApiRequest) -> dict[str, object]:
    config = AppConfig.from_env()
    try:
        request = TripPlanRequest.from_mapping(
            {
                "origin_city": payload.origin_city,
                "destination_city": payload.destination_city,
                "departure_date": payload.departure_date,
                "return_date": payload.return_date,
                "passenger_count": payload.passenger_count,
                "cabin": payload.cabin,
                "source_market": payload.source_market,
                "target_currency": payload.target_currency,
                "include_shanghai_rail": payload.include_shanghai_rail,
                "rail_connection_city": payload.rail_connection_city,
                "airport_stopover_city": payload.airport_stopover_city,
                "flight_filter": payload.flight_filter,
                "flight_stopover_city": payload.flight_stopover_city,
                "manual_exchange_rates": payload.manual_exchange_rates,
            }
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        providers_to_query = providers_from_names(payload.provider_names)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    currency_converter = build_currency_converter(
        exchange_rates=config.exchange_rates,
        exchange_rate_source=config.exchange_rate_source,
        cache_path=config.exchange_rate_cache_path,
        cache_ttl_seconds=config.exchange_rate_cache_ttl_seconds,
        api_base_url=config.exchange_rate_api_base_url,
        timeout_seconds=config.exchange_rate_timeout_seconds,
    )
    planner = TripPlanner(
        providers_to_query,
        timeout_seconds=config.provider_timeout_seconds,
        excluded_carriers=() if payload.include_test_carriers else DEFAULT_EXCLUDED_CARRIERS,
        currency_converter=currency_converter,
        payment_fee_rate=config.payment_fee_rate,
        baggage_fee_amount=config.baggage_fee_amount,
        repository=SqliteSearchRepository(config.database_url),
    )
    context = ProviderContext(
        credentials=config.provider_secret_map(),
        timeout_seconds=config.provider_timeout_seconds,
    )
    result = await planner.plan(request, context)
    return result.to_dict()


def _search_request(payload: SearchApiRequest, config: AppConfig) -> SearchRequest:
    data: dict[str, Any] = {
        "origin": payload.origin,
        "destination": payload.destination,
        "departure_date": payload.departure_date,
        "return_date": payload.return_date,
        "passenger_count": payload.passenger_count,
        "cabin": payload.cabin,
        "allowed_markets": payload.allowed_markets,
        "allowed_currencies": payload.allowed_currencies,
        "stopovers": payload.stopovers,
        "date_flexibility_days": payload.date_flexibility_days,
        "max_layover_hours": payload.max_layover_hours,
        "include_split_ticket": payload.include_split_ticket,
        "include_self_transfer": payload.include_self_transfer,
        "include_hidden_city": payload.include_hidden_city,
    }
    return SearchRequest.from_mapping(
        data,
        default_markets=config.default_markets,
        default_currencies=config.default_currencies,
    )


def _excluded_carriers(payload: SearchApiRequest) -> tuple[str, ...]:
    carriers: tuple[str, ...] = () if payload.include_test_carriers else DEFAULT_EXCLUDED_CARRIERS
    return normalize_carrier_codes(carriers + payload.exclude_carriers)


def _aggregate_response(
    repository: SqliteSearchRepository,
    request: SearchRequest,
    current_offers: tuple[Offer, ...],
    *,
    currency_converter: CurrencyConverter,
    payment_fee_rate: Decimal,
    baggage_fee_amount: Decimal,
) -> dict[str, object]:
    historical_offers = tuple(
        offer_snapshot.offer
        for snapshot in repository.list_route_snapshots(request)
        for offer_snapshot in snapshot.offers
    )
    target_currency = request.allowed_currencies[0]
    offers = _deduplicate_offers(tuple(historical_offers) + tuple(current_offers))
    priced = _price_aggregate_offers(
        offers,
        target_currency=target_currency,
        currency_converter=currency_converter,
        payment_fee_rate=payment_fee_rate,
        baggage_fee_amount=baggage_fee_amount,
    )
    ranked = rank_offers(priced)
    recommendation_offers = tuple(
        offer for offer in ranked if not _is_unconverted_foreign_offer(offer, target_currency)
    )
    recommendations = SearchOrchestrator([])._recommend(recommendation_offers)
    providers = sorted({offer.provider for offer in ranked})
    unconverted_offer_count = sum(
        1 for offer in ranked if _is_unconverted_foreign_offer(offer, target_currency)
    )
    return {
        "aggregate_offers": [offer.to_dict() for offer in ranked],
        "aggregate_recommendations": recommendations.to_dict(),
        "aggregate": {
            "offer_count": len(ranked),
            "provider_count": len(providers),
            "providers": providers,
            "target_currency": target_currency,
            "unconverted_offer_count": unconverted_offer_count,
        },
    }


def _price_aggregate_offers(
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
        if offer.currency.upper() == target_currency.upper():
            if offer.comparable_amount is None:
                priced.extend(
                    apply_comparable_pricing(
                        (offer,),
                        target_currency=target_currency,
                        converter=currency_converter,
                        payment_fee_rate=payment_fee_rate,
                        baggage_fee_amount=baggage_fee_amount,
                    )
                )
            else:
                priced.append(offer)
            continue
        converted = apply_comparable_pricing(
            (offer,),
            target_currency=target_currency,
            converter=currency_converter,
            payment_fee_rate=payment_fee_rate,
            baggage_fee_amount=baggage_fee_amount,
        )[0]
        if converted.currency.upper() == target_currency.upper():
            priced.append(converted)
        else:
            priced.append(offer.model_copy(update={"comparable_amount": None}))
    return tuple(priced)


def _is_unconverted_foreign_offer(offer: Offer, target_currency: str) -> bool:
    return offer.total_amount is not None and offer.currency.upper() != target_currency.upper()


def _deduplicate_offers(offers: tuple[Offer, ...]) -> tuple[Offer, ...]:
    seen: set[tuple[object, ...]] = set()
    deduped: list[Offer] = []
    for offer in offers:
        segments = tuple(getattr(offer, "segments", ()))
        segment_key = tuple(
            (
                getattr(segment, "origin", None),
                getattr(segment, "destination", None),
                getattr(segment, "departure_date", None),
                getattr(segment, "marketing_carrier", None),
                getattr(segment, "flight_number", None),
            )
            for segment in segments
        )
        key = (
            getattr(offer, "provider", None),
            getattr(offer, "source_market", None),
            getattr(offer, "currency", None),
            str(getattr(offer, "total_amount", None)),
            getattr(offer, "booking_link", None),
            segment_key,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(offer)
    return tuple(deduped)


WEB_UI_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ReverseFlightTickets</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #1e2528;
      --muted: #5c666b;
      --line: #d8dee2;
      --surface: #f7f8f5;
      --panel: #ffffff;
      --accent: #007c89;
      --accent-dark: #005e68;
      --warn: #a35d00;
      --danger: #b3261e;
      --ok: #256d3b;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      font-family: Inter, Segoe UI, Roboto, Arial, sans-serif;
      font-size: 15px;
      line-height: 1.45;
      color: var(--ink);
      background: var(--surface);
    }

    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 64px;
      padding: 0 28px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }

    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 700;
      letter-spacing: 0;
    }

    main {
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px;
    }

    form {
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: 16px;
      padding: 20px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--panel);
      box-shadow: 0 14px 40px rgba(30, 37, 40, 0.06);
    }

    label,
    .field {
      display: grid;
      gap: 6px;
    }

    label,
    .field-label {
      font-size: 12px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
    }

    input,
    select,
    textarea {
      min-height: 44px;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 9px 12px;
      font: inherit;
      color: var(--ink);
      background: #ffffff;
    }

    input:focus,
    select:focus,
    textarea:focus {
      outline: 2px solid rgba(0, 124, 137, 0.18);
      border-color: var(--accent);
    }

    textarea {
      min-height: 150px;
      resize: vertical;
      font-family: Consolas, Menlo, monospace;
      font-size: 13px;
      line-height: 1.4;
    }

    button {
      min-height: 40px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      padding: 8px 14px;
      font: inherit;
      font-weight: 700;
      color: #ffffff;
      background: var(--accent);
      cursor: pointer;
    }

    button:hover {
      background: var(--accent-dark);
    }

    button:disabled {
      cursor: wait;
      opacity: 0.72;
    }

    .span-2 { grid-column: span 2; }
    .span-3 { grid-column: span 3; }
    .span-4 { grid-column: span 4; }
    .span-6 { grid-column: span 6; }
    .span-12 { grid-column: span 12; }
    .trip-route-field { grid-column: span 3; }
    .trip-date-field { grid-column: span 2; }
    .trip-small-field { grid-column: span 1; }
    .trip-control-field { grid-column: span 3; }
    .trip-filter-field { grid-column: span 3; }

    .toggles,
    .providers {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px 16px;
    }

    .choice {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 32px;
      font-size: 14px;
      font-weight: 500;
      color: var(--ink);
      text-transform: none;
    }

    .choice input {
      min-height: 16px;
      width: 16px;
      accent-color: var(--accent);
    }

    .option-picker {
      position: relative;
      display: grid;
    }

    .option-picker input[type="search"] {
      padding-right: 34px;
      cursor: pointer;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .option-picker::after {
      content: "";
      position: absolute;
      top: 17px;
      right: 13px;
      width: 8px;
      height: 8px;
      border-right: 2px solid var(--muted);
      border-bottom: 2px solid var(--muted);
      transform: rotate(45deg);
      pointer-events: none;
    }

    .option-list {
      position: absolute;
      z-index: 20;
      top: calc(100% + 6px);
      left: 0;
      right: 0;
      display: none;
      gap: 6px;
      max-height: 280px;
      overflow-y: auto;
      padding: 6px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #ffffff;
      box-shadow: 0 18px 42px rgba(30, 37, 40, 0.16);
    }

    .option-picker[data-open="true"] .option-list {
      display: grid;
    }

    button.option-row {
      display: grid;
      gap: 2px;
      justify-items: start;
      min-height: 48px;
      width: 100%;
      border-color: transparent;
      padding: 8px 10px;
      color: var(--ink);
      background: #ffffff;
      text-align: left;
    }

    button.option-row:hover {
      border-color: #b8d9dd;
      color: var(--accent-dark);
      background: #eef8f9;
    }

    button.option-row[aria-selected="true"] {
      border-color: var(--accent);
      color: var(--accent-dark);
      background: #e5f3f5;
    }

    .option-meta {
      font-size: 12px;
      font-weight: 500;
      color: var(--muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .trip-actions {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 14px;
      padding-top: 4px;
    }

    .option-empty {
      padding: 8px;
      font-size: 13px;
      font-weight: 600;
      color: var(--muted);
      text-transform: none;
    }

    .toolbar {
      display: flex;
      justify-content: flex-end;
      align-items: end;
      gap: 8px;
    }

    .import-panel {
      margin-top: 18px;
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: 14px;
      padding: 18px;
      border: 1px solid var(--line);
      background: var(--panel);
    }

    .utility-panel {
      margin-top: 18px;
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: 14px;
      padding: 18px;
      border: 1px solid var(--line);
      background: var(--panel);
    }

    .subhead {
      grid-column: span 12;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      font-size: 14px;
      font-weight: 800;
    }

    .hint {
      font-size: 13px;
      font-weight: 500;
      color: var(--muted);
    }

    .secondary {
      border-color: var(--line);
      color: var(--accent-dark);
      background: #ffffff;
    }

    .secondary:hover {
      background: #f0f6f7;
    }

    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 340px;
      gap: 18px;
      margin-top: 18px;
      align-items: start;
    }

    section {
      border: 1px solid var(--line);
      background: #ffffff;
    }

    .section-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 46px;
      padding: 0 14px;
      border-bottom: 1px solid var(--line);
      font-size: 14px;
      font-weight: 800;
    }

    .status {
      font-size: 13px;
      font-weight: 600;
      color: var(--muted);
    }

    .table-wrap {
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 880px;
    }

    th,
    td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }

    th {
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      background: #fafafa;
    }

    a {
      color: var(--accent-dark);
      font-weight: 700;
    }

    .recommendations {
      display: grid;
      gap: 10px;
      padding: 12px;
    }

    .rec {
      display: grid;
      gap: 6px;
      min-height: 74px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fcfcfa;
    }

    .rec-title {
      font-size: 12px;
      font-weight: 800;
      color: var(--muted);
      text-transform: uppercase;
    }

    .rec-main {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      font-weight: 800;
    }

    .risk {
      color: var(--warn);
    }

    .summary-text {
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fcfcfa;
      font-weight: 700;
    }

    .link-list {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .empty,
    .error {
      padding: 18px;
      color: var(--muted);
    }

    .error {
      color: var(--danger);
    }

    @media (max-width: 920px) {
      main {
        padding: 14px;
      }

      form,
      .import-panel,
      .utility-panel,
      .layout {
        grid-template-columns: 1fr;
      }

      .span-2,
      .span-3,
      .span-4,
      .span-6,
      .span-12 {
        grid-column: span 1;
      }

      .trip-route-field,
      .trip-date-field,
      .trip-small-field,
      .trip-control-field,
      .trip-filter-field {
        grid-column: span 1;
      }

      .layout {
        gap: 14px;
      }
    }

    /* Template-aligned product shell. Kept local so the web UI works offline. */
    body {
      background:
        radial-gradient(circle at top left, rgba(173, 199, 247, 0.34), transparent 30%),
        linear-gradient(180deg, #f7f9fb 0%, #edf2f7 100%);
    }

    .app-header {
      position: fixed;
      z-index: 50;
      top: 0;
      left: 0;
      right: 0;
      min-height: 64px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(12px);
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .brand-mark {
      display: inline-grid;
      place-items: center;
      width: 36px;
      height: 36px;
      border-radius: 12px;
      color: #ffffff;
      background: #002045;
      font-size: 13px;
      font-weight: 900;
      letter-spacing: -0.04em;
    }

    .brand-title {
      display: grid;
      gap: 1px;
    }

    .brand-title strong {
      color: #002045;
      font-size: 22px;
      line-height: 1;
      letter-spacing: -0.04em;
    }

    .brand-title span {
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }

    .top-nav {
      display: flex;
      gap: 18px;
      align-items: center;
    }

    .top-nav a {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-decoration: none;
      text-transform: uppercase;
    }

    .top-nav a.active {
      color: #0058be;
    }

    .top-nav a.future-link::after,
    .future-chip::before {
      content: "后续评估";
      display: inline-flex;
      margin-left: 6px;
      border: 1px solid #c4c6cf;
      border-radius: 999px;
      padding: 2px 6px;
      color: #5c666b;
      background: #f7f9fb;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0;
      text-transform: none;
    }

    main.app-shell {
      display: grid;
      grid-template-columns: 340px minmax(0, 1fr) 300px;
      gap: 24px;
      max-width: 1600px;
      height: 100vh;
      margin: 0 auto;
      padding: 84px 24px 28px;
      overflow: hidden;
    }

    .left-rail,
    .comparison-panel,
    .right-rail {
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      scrollbar-width: thin;
    }

    .left-rail,
    .right-rail {
      display: flex;
      flex-direction: column;
      gap: 16px;
      padding-bottom: 28px;
    }

    .app-card,
    .plan-card,
    .comparison-panel {
      border: 1px solid #c4c6cf;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: 0 18px 48px rgba(0, 32, 69, 0.08);
    }

    form.search-form,
    form.tool-form {
      display: flex !important;
      flex-direction: column;
      align-items: stretch;
      gap: 14px;
      margin: 0;
      padding: 18px;
      border-radius: 18px;
      box-shadow: none;
      overflow-x: clip;
    }

    .tool-form {
      border: 0;
      background: transparent;
    }

    .search-form .subhead,
    .tool-form .subhead {
      display: block;
      flex: 0 0 auto;
      min-height: 58px;
      margin: 0 0 6px;
      padding: 0;
      border: 0;
      line-height: normal;
      overflow: visible;
      position: relative;
      z-index: 1;
    }

    .search-form .subhead > span:first-child,
    .tool-form .subhead > span:first-child {
      display: block;
      color: #191c1e;
      font-size: 24px;
      font-weight: 900;
      line-height: 1.12;
      letter-spacing: -0.04em;
    }

    .search-form .subhead .hint,
    .tool-form .subhead .hint {
      display: block;
      margin-top: 7px;
      font-size: 13px;
      font-weight: 700;
      line-height: 1.45;
      letter-spacing: 0;
      text-transform: none;
    }

    .form-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 10px;
    }

    .form-row > *,
    .search-form label,
    .search-form .field,
    .tool-form label {
      min-width: 0;
    }

    .search-form label,
    .search-form .field,
    .tool-form label,
    .rates-card label {
      display: flex !important;
      flex-direction: column;
      gap: 6px;
      color: #74777f;
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.08em;
      line-height: 1.2;
      overflow: visible;
    }

    .search-form .field-label {
      display: block;
      margin: 0;
      line-height: 14px;
    }

    .search-form input,
    .search-form select,
    .tool-form input,
    .tool-form textarea,
    .tool-form select,
    .rates-card input {
      min-height: 42px;
      border-color: #c4c6cf;
      border-radius: 12px;
      background: #ffffff;
      font-size: 14px;
      line-height: 1.25;
      min-width: 0;
      flex: 0 0 auto;
    }

    .search-form .option-picker input[type="search"],
    .search-form select {
      font-size: 13.5px;
    }

    .primary-action {
      width: 100%;
      min-height: 46px;
      border-color: #002045;
      border-radius: 14px;
      background: #002045;
      box-shadow: 0 12px 28px rgba(0, 32, 69, 0.18);
    }

    .primary-action:hover {
      background: #1a365d;
    }

    .provider-list,
    .compact-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
      align-items: center;
    }

    .rates-card,
    .future-panel,
    .summary-panel,
    .route-panel {
      padding: 16px;
    }

    .card-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin: 0 0 12px;
      color: #002045;
      font-size: 12px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .comparison-panel {
      padding: 0;
      overflow: hidden;
    }

    .comparison-scroll {
      height: 100%;
      overflow-y: auto;
      padding: 0 4px 28px 0;
    }

    .comparison-header {
      position: sticky;
      z-index: 5;
      top: 0;
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 18px;
      padding: 22px 24px 18px;
      border-bottom: 1px solid #c4c6cf;
      background: rgba(247, 249, 251, 0.94);
      backdrop-filter: blur(12px);
    }

    .comparison-header h2 {
      margin: 0;
      color: #002045;
      font-size: 44px;
      line-height: 1;
      letter-spacing: -0.06em;
    }

    .comparison-header p {
      margin: 8px 0 0;
      color: #5c666b;
      font-size: 15px;
    }

    .sort-pills {
      display: flex;
      gap: 4px;
      border-radius: 14px;
      padding: 4px;
      background: #e6e8ea;
    }

    .sort-pills button {
      min-height: 34px;
      border: 0;
      border-radius: 10px;
      padding: 6px 12px;
      color: #74777f;
      background: transparent;
      font-size: 12px;
      box-shadow: none;
    }

    .sort-pills button.active {
      color: #002045;
      background: #ffffff;
      box-shadow: 0 6px 18px rgba(0, 32, 69, 0.12);
    }

    .sort-pills button:disabled {
      cursor: default;
    }

    .book-disabled:disabled,
    .summary-panel button:disabled {
      cursor: not-allowed;
    }

    .result-list {
      display: grid;
      gap: 18px;
      padding: 20px 20px 28px;
    }

    .empty-state,
    .error,
    .empty {
      border: 1px dashed #c4c6cf;
      border-radius: 16px;
      padding: 18px;
      color: #5c666b;
      background: #ffffff;
      font-weight: 700;
    }

    .plan-card {
      overflow: hidden;
      transition: transform 0.16s ease, box-shadow 0.16s ease;
    }

    .plan-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 22px 58px rgba(0, 32, 69, 0.12);
    }

    .plan-card.recommended {
      border-color: #0d9488;
      box-shadow: 0 20px 56px rgba(13, 148, 136, 0.16);
    }

    .plan-card-main {
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(260px, 0.72fr);
    }

    .timeline-pane {
      padding: 22px;
    }

    .price-pane {
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 18px;
      border-left: 1px solid #c4c6cf;
      padding: 22px;
      background: rgba(242, 244, 246, 0.78);
    }

    .plan-meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 18px;
    }

    .plan-title {
      margin: 10px 0 2px;
      color: #191c1e;
      font-size: 20px;
      line-height: 1.2;
      letter-spacing: -0.03em;
    }

    .status-badge,
    .kind-badge {
      display: inline-flex;
      align-items: center;
      width: fit-content;
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .status-priced {
      color: #0d6b62;
      background: #dff8f3;
    }

    .status-needs_exchange_rate,
    .status-needs_manual_flight_price {
      color: #9a5b00;
      background: #fff2cc;
    }

    .status-no_flights {
      color: #93000a;
      background: #ffdad6;
    }

    .kind-badge {
      color: #2d476f;
      background: #d6e3ff;
    }

    .timeline-list {
      display: grid;
      gap: 0;
    }

    .timeline-item {
      position: relative;
      display: grid;
      grid-template-columns: 26px minmax(0, 1fr);
      gap: 14px;
      min-height: 64px;
    }

    .timeline-item:not(:last-child)::before {
      content: "";
      position: absolute;
      left: 12px;
      top: 28px;
      bottom: -8px;
      border-left: 2px solid #3b82f6;
    }

    .timeline-item.rail:not(:last-child)::before {
      border-left: 2px dashed #0d9488;
    }

    .timeline-dot {
      z-index: 1;
      display: grid;
      place-items: center;
      width: 26px;
      height: 26px;
      border: 2px solid #002045;
      border-radius: 50%;
      color: #002045;
      background: #ffffff;
      font-size: 11px;
      font-weight: 900;
    }

    .timeline-item.rail .timeline-dot {
      border-color: #0d9488;
      color: #0d9488;
    }

    .timeline-copy {
      padding-bottom: 18px;
    }

    .timeline-copy strong {
      display: block;
      color: #191c1e;
      font-size: 15px;
    }

    .timeline-copy span,
    .timeline-copy small {
      display: block;
      color: #5c666b;
      font-size: 13px;
    }

    .price-label {
      color: #74777f;
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .price-value {
      margin-top: 4px;
      color: #002045;
      font-size: 30px;
      font-weight: 900;
      letter-spacing: -0.04em;
    }

    .breakdown {
      display: grid;
      gap: 8px;
      margin-top: 18px;
    }

    .breakdown-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: #43474e;
      font-size: 14px;
    }

    .action-stack {
      display: grid;
      gap: 8px;
    }

    .book-disabled {
      border-color: #0d9488;
      color: #ffffff;
      background: #0d9488;
    }

    .outline-action {
      border-color: #002045;
      color: #002045;
      background: #ffffff;
    }

    .provider-details {
      border-top: 1px solid #c4c6cf;
      padding: 12px 22px 18px;
      background: #ffffff;
    }

    .provider-details summary {
      cursor: pointer;
      color: #002045;
      font-weight: 900;
    }

    .candidate-grid,
    .offer-grid {
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }

    .candidate-row,
    .offer-row {
      display: grid;
      grid-template-columns: 1.25fr 0.8fr 0.8fr 1fr;
      gap: 10px;
      border: 1px solid #e0e3e5;
      border-radius: 12px;
      padding: 10px;
      color: #43474e;
      background: #f7f9fb;
      font-size: 13px;
    }

    .summary-panel {
      color: #ffffff;
      border-color: #002045;
      background: linear-gradient(145deg, #002045, #1a365d);
      box-shadow: 0 22px 54px rgba(0, 32, 69, 0.24);
    }

    .summary-price {
      color: #ffffff;
      font-size: 31px;
      font-weight: 900;
      letter-spacing: -0.05em;
    }

    .summary-muted {
      color: rgba(255, 255, 255, 0.72);
      font-size: 12px;
      font-weight: 700;
    }

    .summary-stats {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin: 16px 0;
    }

    .summary-stat {
      border-radius: 12px;
      padding: 10px;
      background: rgba(255, 255, 255, 0.12);
    }

    .route-panel {
      min-height: 220px;
      overflow: hidden;
      background:
        linear-gradient(145deg, rgba(255, 255, 255, 0.74), rgba(255, 255, 255, 0.96)),
        repeating-linear-gradient(35deg, rgba(0, 32, 69, 0.05) 0 2px, transparent 2px 18px);
    }

    .route-map {
      position: relative;
      min-height: 150px;
      overflow: hidden;
      border: 1px solid #e0e3e5;
      border-radius: 14px;
      background:
        radial-gradient(circle at 14% 20%, rgba(255, 255, 255, 0.8), transparent 26%),
        linear-gradient(145deg, #d9ecf7, #edf5f9);
    }

    .route-map svg {
      display: block;
      width: 100%;
      height: clamp(136px, 18vw, 160px);
      border-radius: 14px;
    }

    .map-grid {
      stroke: rgba(0, 32, 69, 0.12);
      stroke-width: 0.45;
    }

    .map-route {
      fill: none;
      stroke: #0058be;
      stroke-width: 1.8;
      stroke-linecap: round;
      stroke-linejoin: round;
    }

    .map-rail {
      stroke: #0d9488;
      stroke-dasharray: 3 2;
    }

    .map-point {
      fill: #002045;
      stroke: #ffffff;
      stroke-width: 1.5;
    }

    .map-point.connection {
      fill: #0d9488;
    }

    .map-marker-number {
      fill: #ffffff;
      font-size: 4px;
      font-weight: 900;
      text-anchor: middle;
      dominant-baseline: central;
      pointer-events: none;
    }

    .map-scope {
      margin-top: 10px;
      color: #43474e;
      font-size: 12px;
      font-weight: 800;
    }

    .route-map-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 10px;
    }

    .route-map-legend span {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      border: 1px solid #d3dde6;
      border-radius: 999px;
      padding: 4px 8px;
      color: #002045;
      background: rgba(255, 255, 255, 0.78);
      font-size: 11px;
      font-weight: 900;
      line-height: 1;
    }

    .future-panel ul {
      display: grid;
      gap: 8px;
      margin: 0;
      padding-left: 18px;
      color: #43474e;
      font-size: 13px;
      font-weight: 650;
    }

    .mobile-nav {
      display: none;
    }

    @media (max-width: 1180px) {
      main.app-shell {
        grid-template-columns: minmax(330px, 360px) minmax(0, 1fr);
        height: auto;
        overflow: visible;
      }

      .right-rail {
        grid-column: 1 / -1;
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }

    @media (max-width: 1080px) and (min-width: 841px) {
      main.app-shell {
        grid-template-columns: 360px minmax(0, 1fr);
        gap: 18px;
        padding-left: 18px;
        padding-right: 18px;
      }

      .search-form .form-row {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 840px) {
      .app-header {
        padding: 0 14px;
      }

      .top-nav {
        display: none;
      }

      main.app-shell {
        grid-template-columns: 1fr;
        padding: 78px 14px 92px;
      }

      .search-form .form-row {
        grid-template-columns: 1fr;
      }

      .comparison-header,
      .plan-card-main,
      .right-rail {
        grid-template-columns: 1fr;
      }

      .comparison-header {
        align-items: start;
      }

      .price-pane {
        border-top: 1px solid #c4c6cf;
        border-left: 0;
      }

      .candidate-row,
      .offer-row {
        grid-template-columns: 1fr;
      }

      .mobile-nav {
        position: fixed;
        z-index: 60;
        right: 14px;
        bottom: 14px;
        left: 14px;
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 6px;
        border: 1px solid #c4c6cf;
        border-radius: 18px;
        padding: 8px;
        background: rgba(255, 255, 255, 0.94);
        box-shadow: 0 18px 48px rgba(0, 32, 69, 0.16);
        backdrop-filter: blur(12px);
      }

      .mobile-nav a {
        border-radius: 12px;
        padding: 8px 4px;
        color: #43474e;
        font-size: 12px;
        font-weight: 900;
        text-align: center;
        text-decoration: none;
      }

      .mobile-nav a.active {
        color: #0058be;
        background: #d8e2ff;
      }
    }
  </style>
</head>
<body>
  <header class="app-header">
    <div class="brand">
      <span class="brand-mark">RFT</span>
      <div class="brand-title">
        <strong>ReverseFlight</strong>
        <span>Trip plan & comparison</span>
      </div>
    </div>
    <nav class="top-nav" aria-label="Primary">
      <a class="active" href="#search">Search</a>
      <a class="future-link" href="#future">查询暂存</a>
      <a href="#rates">Rates</a>
    </nav>
  </header>
  <main class="app-shell">
    <aside class="left-rail" id="search">
      <form id="trip-plan-form" class="app-card search-form">
        <div class="subhead">
          <span>Plan Trip</span>
          <span class="hint">城市级比价：直飞、铁路接驳、机场中转统一比较。</span>
        </div>
        <div class="field" data-option-picker="trip_origin_city">
          <div class="field-label">Origin</div>
          <div class="option-picker"></div>
        </div>
        <div class="field" data-option-picker="trip_destination_city">
          <div class="field-label">Destination</div>
          <div class="option-picker"></div>
        </div>
        <div class="form-row">
          <label>Departure
            <input id="trip_departure_date" type="date" required>
          </label>
          <label>Return
            <input id="trip_return_date" type="date" required>
          </label>
        </div>
        <div class="form-row">
          <label>Passengers
            <input id="trip_passenger_count" type="number" min="1" value="1">
          </label>
          <label>Cabin
            <select id="trip_cabin">
              <option value="economy">Economy</option>
              <option value="premium_economy">Premium economy</option>
              <option value="business">Business</option>
              <option value="first">First</option>
            </select>
          </label>
        </div>
        <div class="form-row">
          <div class="field" data-option-picker="trip_source_market">
            <div class="field-label">Sales region</div>
            <div class="option-picker"></div>
          </div>
          <div class="field" data-option-picker="trip_target_currency">
            <div class="field-label">Currency</div>
            <div class="option-picker"></div>
          </div>
        </div>
        <label>Connection type
          <select id="trip_connection_type">
            <option value="rail">铁路接驳到其他机场城市</option>
            <option value="none">仅出发城市机场</option>
            <option value="airport">机场城市中转</option>
          </select>
        </label>
        <div class="field" data-option-picker="trip_connection_city">
          <div class="field-label">Connection city</div>
          <div class="option-picker"></div>
        </div>
        <label>Flight filter
          <select id="trip_flight_filter">
            <option value="all">全部航班选项</option>
            <option value="direct">仅看直飞</option>
            <option value="via_city">仅看指定城市中转</option>
          </select>
        </label>
        <div class="field" data-option-picker="trip_flight_stopover_city">
          <div class="field-label">Via city</div>
          <div class="option-picker"></div>
        </div>
        <label>Manual rates
          <input id="trip_manual_exchange_rates" placeholder="USD:CNY=7.20">
        </label>
        <div class="provider-list" id="trip_providers"></div>
        <label class="choice"><input id="trip_include_test_carriers" type="checkbox">Test carriers</label>
        <button class="primary-action" id="trip-plan-button" type="submit">Update Results</button>
      </form>

      <section class="app-card rates-card" id="rates">
        <h3 class="card-title">Exchange Rates</h3>
        <form id="currency-form" class="tool-form">
          <div class="form-row">
            <label>Amount
              <input id="fx_amount" inputmode="decimal" value="1000">
            </label>
            <label>From
              <input id="fx_from" value="CNY">
            </label>
          </div>
          <label>To
            <input id="fx_to" value="USD">
          </label>
          <button class="secondary" id="fx-button" type="submit">Convert</button>
          <div class="status" id="fx_result">-</div>
        </form>
      </section>

      <details class="app-card rates-card">
        <summary class="card-title">Import Browser Offers</summary>
        <form id="browser-import-form" class="tool-form">
          <label>Export file
            <input id="browser_file" type="file" accept=".json,.csv,application/json,text/csv">
          </label>
          <div class="form-row">
            <label>Target currency
              <input id="browser_target_currency" placeholder="CNY">
            </label>
            <label class="choice"><input id="browser_save_snapshot" type="checkbox" checked>Snapshot</label>
          </div>
          <label>Export content
            <textarea id="browser_content" placeholder="Paste userscript JSON or CSV here"></textarea>
          </label>
          <div class="compact-actions">
            <button class="secondary" id="clear-browser-import" type="button">Clear</button>
            <button id="browser-import-button" type="submit">Import offers</button>
          </div>
        </form>
      </details>
    </aside>

    <section class="comparison-panel">
      <div class="comparison-scroll">
        <div class="comparison-header">
          <div>
            <h2>Comparison</h2>
            <p><span id="offer-count">0 plans / 0 offers</span> for the selected route.</p>
          </div>
          <div class="sort-pills" aria-label="Sort modes">
            <button class="active" type="button" disabled>Best Match</button>
            <button type="button" disabled>Cheapest <span class="future-chip"></span></button>
            <button type="button" disabled>Fastest <span class="future-chip"></span></button>
          </div>
        </div>
        <div class="result-list" id="results">
          <div class="empty-state">输入城市、日期和比价币种后点击 Update Results。</div>
        </div>
      </div>
    </section>

    <aside class="right-rail">
      <section class="app-card summary-panel">
        <h3 class="card-title" style="color: rgba(255,255,255,.78);">Plan Overview</h3>
        <div class="summary-price" id="summary-price">-</div>
        <div class="summary-muted" id="aggregate-count">current only</div>
        <div class="summary-stats">
          <div class="summary-stat">
            <div class="summary-muted">Plans</div>
            <strong id="summary-plan-count">0</strong>
          </div>
          <div class="summary-stat">
            <div class="summary-muted">Flight offers</div>
            <strong id="summary-offer-count">0</strong>
          </div>
        </div>
        <button class="secondary" type="button" disabled>Generate PDF Report <span class="future-chip"></span></button>
        <div class="recommendations" id="recommendations"><div class="empty">No data.</div></div>
      </section>

      <section class="app-card route-panel">
        <h3 class="card-title">Route Map</h3>
        <div class="route-map" id="route-map" aria-label="Route map"></div>
        <div class="route-map-legend" id="route-map-legend"></div>
        <div class="map-scope" id="route-map-scope">按城市选择自动切换区域视野。</div>
        <p class="hint">简化地图用于判断相对位置；真实地理边界、机场点位和缩放控件后续评估。</p>
      </section>

      <section class="app-card future-panel" id="future">
        <h3 class="card-title">Template Items To Evaluate</h3>
        <ul>
          <li>Book This Plan 实际下单/订单交接流程。</li>
          <li>Generate PDF Report 报告导出。</li>
          <li>查询暂存、历史搜索和行程快照页面。</li>
          <li>实时汇率波动提醒。</li>
          <li>卡片内手动价格保存回后端。</li>
        </ul>
      </section>
    </aside>
  </main>
  <nav class="mobile-nav" aria-label="Mobile">
    <a class="active" href="#search">Search</a>
    <a href="#future">暂存</a>
    <a href="#rates">Rates</a>
  </nav>
  <script>
    const state = { providers: [], browserFilename: null, optionPickers: {}, tripMetadata: null };

    const optionPickerConfigs = {
      trip_origin_city: {
        label: "origin city",
        defaultValue: "Nanjing",
        options: [
          { value: "Nanjing", label: "Nanjing / NKG", meta: "NKG", keywords: ["nkg"] }
        ]
      },
      trip_destination_city: {
        label: "destination city",
        defaultValue: "Taipei",
        options: [
          { value: "Taipei", label: "Taipei / TPE / TSA", meta: "TPE / TSA", keywords: ["tpe", "tsa"] }
        ]
      },
      trip_source_market: {
        label: "sales region",
        defaultValue: "CN",
        options: [
          { value: "CN", label: "中国大陆 (CN)", meta: "Mainland China point of sale" }
        ]
      },
      trip_target_currency: {
        label: "comparison currency",
        defaultValue: "CNY",
        options: [
          { value: "CNY", label: "CNY", meta: "Chinese yuan" }
        ]
      },
      trip_connection_city: {
        label: "connection city",
        defaultValue: "Shanghai",
        allowEmpty: true,
        emptyValue: "",
        emptyLabel: "No connection city",
        options: [
          { value: "Shanghai", label: "Shanghai / PVG / SHA", meta: "Rail estimate available", keywords: ["pvg", "sha"] }
        ]
      },
      trip_flight_stopover_city: {
        label: "flight stopover city",
        defaultValue: "",
        allowEmpty: true,
        emptyValue: "",
        emptyLabel: "No flight stopover city",
        options: []
      }
    };

    const csv = (value) => value.split(",").map((part) => part.trim()).filter(Boolean);
    const text = (value) => value === null || value === undefined || value === "" ? "-" : String(value);
    const cityCoordinates = {
      Nanjing: { label: "Nanjing", lat: 32.06, lon: 118.78 },
      Shanghai: { label: "Shanghai", lat: 31.23, lon: 121.47 },
      Taipei: { label: "Taipei", lat: 25.03, lon: 121.57 },
      Beijing: { label: "Beijing", lat: 39.9, lon: 116.41 },
      Guangzhou: { label: "Guangzhou", lat: 23.13, lon: 113.26 },
      Shenzhen: { label: "Shenzhen", lat: 22.54, lon: 114.06 },
      Hangzhou: { label: "Hangzhou", lat: 30.27, lon: 120.16 },
      Xiamen: { label: "Xiamen", lat: 24.48, lon: 118.08 },
      Fuzhou: { label: "Fuzhou", lat: 26.08, lon: 119.3 },
      Chengdu: { label: "Chengdu", lat: 30.57, lon: 104.07 },
      Chongqing: { label: "Chongqing", lat: 29.56, lon: 106.55 },
      Wuhan: { label: "Wuhan", lat: 30.59, lon: 114.31 },
      Qingdao: { label: "Qingdao", lat: 36.07, lon: 120.38 },
      "Xi'an": { label: "Xi'an", lat: 34.34, lon: 108.94 },
      "Hong Kong": { label: "Hong Kong", lat: 22.32, lon: 114.17 },
      Macau: { label: "Macau", lat: 22.2, lon: 113.54 },
      NewYork: { label: "New York", lat: 40.71, lon: -74.01 },
      "New York": { label: "New York", lat: 40.71, lon: -74.01 }
    };

    async function init() {
      const [providers, metadata] = await Promise.all([
        fetch("/api/providers").then((response) => response.json()),
        fetch("/api/trip-plan/metadata").then((response) => response.json())
      ]);
      state.providers = providers.providers;
      state.tripMetadata = metadata;
      hydrateTripOptionConfigs(metadata);
      setupOptionPickers();
      renderProviders();
      setupTripPlanDependencies();
      updateRouteMap();
    }

    function hydrateTripOptionConfigs(metadata) {
      const cityOptions = (metadata.cities || []).map(cityToOption);
      optionPickerConfigs.trip_origin_city.options = cityOptions;
      optionPickerConfigs.trip_destination_city.options = cityOptions;
      optionPickerConfigs.trip_source_market.options = (metadata.markets || []).map((item) => ({
        value: item.value,
        label: `${item.label} (${item.value})`,
        meta: item.meta,
        keywords: [item.value, item.label]
      }));
      optionPickerConfigs.trip_target_currency.options = (metadata.currencies || []).map((item) => ({
        value: item.value,
        label: item.label,
        meta: item.meta,
        keywords: [item.value]
      }));
      optionPickerConfigs.trip_connection_city.options = (metadata.rail_connection_options || []).map(cityToOption);
      optionPickerConfigs.trip_flight_stopover_city.options = cityOptions;
    }

    function cityToOption(item) {
      const airports = item.airports || [];
      return {
        value: item.value,
        label: airports.length ? `${item.label} / ${airports.join("/")}` : item.label,
        meta: airports.length ? airports.join(" / ") : item.value,
        keywords: [...(item.keywords || []), ...airports]
      };
    }

    function renderProviders() {
      const target = document.getElementById("trip_providers");
      target.innerHTML = "";
      state.providers.forEach((provider) => {
        if (provider.research) return;
        const label = document.createElement("label");
        label.className = "choice";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.name = "trip_provider";
        input.value = provider.name;
        input.checked = Boolean(provider.default_enabled);
        label.appendChild(input);
        label.appendChild(document.createTextNode(provider.name));
        target.appendChild(label);
      });
    }

    function setupOptionPickers() {
      Object.entries(optionPickerConfigs).forEach(([id, config]) => {
        const host = document.querySelector(`[data-option-picker="${id}"] .option-picker`);
        if (!host) return;
        host.innerHTML = "";
        const search = document.createElement("input");
        search.id = `${id}_search`;
        search.type = "search";
        search.autocomplete = "off";
        search.placeholder = "Type to filter";
        search.setAttribute("aria-label", `Search ${config.label}`);
        const hidden = document.createElement("input");
        hidden.id = id;
        hidden.type = "hidden";
        const list = document.createElement("div");
        list.className = "option-list";
        list.id = `${id}_options`;
        list.setAttribute("role", "listbox");
        list.setAttribute("aria-label", config.label);
        host.appendChild(search);
        host.appendChild(hidden);
        host.appendChild(list);
        state.optionPickers[id] = {
          config,
          host,
          search,
          hidden,
          list,
          selectedValue: ""
        };
        selectOption(id, config.defaultValue);
        search.addEventListener("input", () => {
          const query = search.value.trim();
          const current = selectedOption(id);
          const exact = findExactOption(pickerOptions(id), query);
          if (exact) {
            state.optionPickers[id].selectedValue = exact.value;
            hidden.value = exact.value;
          } else if (config.allowEmpty && !query) {
            state.optionPickers[id].selectedValue = config.emptyValue || "";
            hidden.value = config.emptyValue || "";
          } else if (!current || query !== current.label) {
            state.optionPickers[id].selectedValue = "";
            hidden.value = "";
          }
          openOptionList(id);
          renderOptionList(id, query);
        });
        search.addEventListener("focus", () => openOptionList(id));
        search.addEventListener("click", () => openOptionList(id));
        search.addEventListener("keydown", (event) => {
          if (event.key === "Escape") closeOptionList(id);
          if (event.key === "ArrowDown") openOptionList(id);
        });
        renderOptionList(id, "");
      });
      document.addEventListener("click", (event) => {
        Object.keys(state.optionPickers).forEach((id) => {
          if (!state.optionPickers[id].host.contains(event.target)) closeOptionList(id);
        });
      });
    }

    function openOptionList(id) {
      state.optionPickers[id].host.dataset.open = "true";
      renderOptionList(id, state.optionPickers[id].search.value);
    }

    function closeOptionList(id) {
      delete state.optionPickers[id].host.dataset.open;
    }

    function renderOptionList(id, query) {
      const picker = state.optionPickers[id];
      const normalizedQuery = query.trim().toLowerCase();
      const options = pickerOptions(id);
      const matches = options.filter((option) => optionMatches(option, normalizedQuery));
      const visibleOptions = matches.length ? matches : options;
      picker.list.innerHTML = "";
      if (!matches.length) {
        const empty = document.createElement("div");
        empty.className = "option-empty";
        empty.textContent = "No matching option. All supported options are shown below.";
        picker.list.appendChild(empty);
      }
      visibleOptions.forEach((option) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "option-row";
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", String(option.value === picker.selectedValue));
        const title = document.createElement("span");
        title.textContent = option.label;
        const meta = document.createElement("span");
        meta.className = "option-meta";
        meta.textContent = option.meta || option.value;
        button.appendChild(title);
        button.appendChild(meta);
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          selectOption(id, option.value);
        });
        picker.list.appendChild(button);
      });
    }

    function optionMatches(option, query) {
      if (!query) return true;
      const haystack = [option.value, option.label, option.meta, ...(option.keywords || [])]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    }

    function pickerOptions(id) {
      const picker = state.optionPickers[id];
      const options = picker.config.options || [];
      if (!picker.config.allowEmpty) return options;
      return [
        {
          value: picker.config.emptyValue || "",
          label: picker.config.emptyLabel || "None",
          meta: "Do not add a connection plan",
          keywords: ["none", "direct"]
        },
        ...options
      ];
    }

    function findExactOption(options, query) {
      const normalizedQuery = query.trim().toLowerCase();
      if (!normalizedQuery) return null;
      return options.find((option) => {
        const values = [option.value, option.label, ...(option.keywords || [])];
        return values.some((value) => String(value).toLowerCase() === normalizedQuery);
      }) || null;
    }

    function selectOption(id, value) {
      const picker = state.optionPickers[id];
      const option = pickerOptions(id).find((item) => item.value === value);
      if (!option) return;
      picker.selectedValue = option.value;
      picker.hidden.value = option.value;
      picker.search.value = option.label;
      renderOptionList(id, "");
      closeOptionList(id);
      picker.hidden.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function selectedOption(id) {
      const picker = state.optionPickers[id];
      return pickerOptions(id).find((item) => item.value === picker.selectedValue) || null;
    }

    function selectedOptionValue(id) {
      const picker = state.optionPickers[id];
      const option = selectedOption(id);
      if (!option) {
        picker.search.focus();
        throw new Error(`Choose a supported ${picker.config.label} from the list.`);
      }
      return option.value;
    }

    function replacePickerOptions(id, options, defaultValue) {
      const picker = state.optionPickers[id];
      picker.config.options = options;
      const value = defaultValue !== undefined ? defaultValue : picker.config.defaultValue;
      if (value !== undefined && pickerOptions(id).some((option) => option.value === value)) {
        selectOption(id, value);
      } else if (picker.config.allowEmpty) {
        selectOption(id, picker.config.emptyValue || "");
      } else if (pickerOptions(id).length) {
        selectOption(id, pickerOptions(id)[0].value);
      } else {
        picker.selectedValue = "";
        picker.hidden.value = "";
        picker.search.value = "";
        renderOptionList(id, "");
      }
    }

    function setupTripPlanDependencies() {
      document.getElementById("trip_connection_type").addEventListener("change", updateConnectionCityOptions);
      document.getElementById("trip_flight_filter").addEventListener("change", updateFlightStopoverOptions);
      ["trip_origin_city", "trip_destination_city"].forEach((id) => {
        state.optionPickers[id].hidden.addEventListener("change", updateConnectionCityOptions);
        state.optionPickers[id].hidden.addEventListener("change", updateFlightStopoverOptions);
        state.optionPickers[id].hidden.addEventListener("change", updateRouteMap);
      });
      state.optionPickers.trip_connection_city.hidden.addEventListener("change", updateRouteMap);
      document.getElementById("trip_connection_type").addEventListener("change", updateRouteMap);
      updateConnectionCityOptions();
      updateFlightStopoverOptions();
    }

    async function updateConnectionCityOptions() {
      const type = document.getElementById("trip_connection_type").value;
      if (type === "none") {
        replacePickerOptions("trip_connection_city", [], "");
        return;
      }
      const origin = selectedOption("trip_origin_city");
      const destination = selectedOption("trip_destination_city");
      if (!origin || !destination) {
        replacePickerOptions("trip_connection_city", [], "");
        return;
      }
      if (type === "airport") {
        const cityOptions = (state.tripMetadata.cities || [])
          .filter((city) => city.value !== origin.value && city.value !== destination.value)
          .map(cityToOption);
        replacePickerOptions("trip_connection_city", cityOptions, cityOptions[0]?.value || "");
        return;
      }
      const params = new URLSearchParams({
        origin_city: origin.value,
        destination_city: destination.value
      });
      const metadata = await fetch(`/api/trip-plan/metadata?${params}`).then((response) => response.json());
      const railOptions = (metadata.rail_connection_options || []).map(cityToOption);
      replacePickerOptions("trip_connection_city", railOptions, railOptions[0]?.value || "");
    }

    function updateFlightStopoverOptions() {
      const filter = document.getElementById("trip_flight_filter").value;
      const picker = state.optionPickers.trip_flight_stopover_city;
      if (filter !== "via_city") {
        replacePickerOptions("trip_flight_stopover_city", [], "");
        picker.search.disabled = true;
        return;
      }
      picker.search.disabled = false;
      const origin = selectedOption("trip_origin_city");
      const destination = selectedOption("trip_destination_city");
      if (!origin || !destination) {
        replacePickerOptions("trip_flight_stopover_city", [], "");
        return;
      }
      const cityOptions = (state.tripMetadata.cities || [])
        .filter((city) => city.value !== origin.value && city.value !== destination.value)
        .map(cityToOption);
      replacePickerOptions("trip_flight_stopover_city", cityOptions, cityOptions[0]?.value || "");
    }

    document.getElementById("trip-plan-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = document.getElementById("trip-plan-button");
      button.disabled = true;
      button.textContent = "Comparing";
      try {
        const provider_names = Array.from(document.querySelectorAll("input[name='trip_provider']:checked")).map((input) => input.value);
        const connectionType = document.getElementById("trip_connection_type").value;
        const connectionCity = selectedOptionValue("trip_connection_city") || null;
        const flightFilter = document.getElementById("trip_flight_filter").value;
        const payload = {
          origin_city: selectedOptionValue("trip_origin_city"),
          destination_city: selectedOptionValue("trip_destination_city"),
          departure_date: document.getElementById("trip_departure_date").value,
          return_date: document.getElementById("trip_return_date").value,
          passenger_count: Number(document.getElementById("trip_passenger_count").value || 1),
          cabin: document.getElementById("trip_cabin").value,
          source_market: selectedOptionValue("trip_source_market"),
          target_currency: selectedOptionValue("trip_target_currency"),
          manual_exchange_rates: csv(document.getElementById("trip_manual_exchange_rates").value),
          include_shanghai_rail: false,
          rail_connection_city: connectionType === "rail" ? connectionCity : null,
          airport_stopover_city: connectionType === "airport" ? connectionCity : null,
          flight_filter: flightFilter,
          flight_stopover_city: flightFilter === "via_city" ? selectedOptionValue("trip_flight_stopover_city") : null,
          include_test_carriers: document.getElementById("trip_include_test_carriers").checked,
          provider_names
        };
        const response = await fetch("/api/trip-plan", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Trip planning failed");
        renderTripPlan(data);
      } catch (error) {
        renderError(error.message);
      } finally {
        button.disabled = false;
        button.textContent = "Update Results";
      }
    });

    document.getElementById("browser_file").addEventListener("change", async (event) => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      state.browserFilename = file.name;
      document.getElementById("browser_content").value = await file.text();
    });

    document.getElementById("clear-browser-import").addEventListener("click", () => {
      state.browserFilename = null;
      document.getElementById("browser_file").value = "";
      document.getElementById("browser_content").value = "";
    });

    document.getElementById("browser-import-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = document.getElementById("browser-import-button");
      button.disabled = true;
      button.textContent = "Importing";
      try {
        const payload = {
          content: document.getElementById("browser_content").value,
          filename: state.browserFilename,
          target_currency: document.getElementById("browser_target_currency").value || null,
          save_snapshot: document.getElementById("browser_save_snapshot").checked
        };
        const response = await fetch("/api/import-browser", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Import failed");
        renderResults(data);
        renderStatus(data);
      } catch (error) {
        renderError(error.message);
      } finally {
        button.disabled = false;
        button.textContent = "Import offers";
      }
    });

    document.getElementById("currency-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = document.getElementById("fx-button");
      const result = document.getElementById("fx_result");
      button.disabled = true;
      button.textContent = "Converting";
      result.textContent = "-";
      try {
        const response = await fetch("/api/currency/convert", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            amount: document.getElementById("fx_amount").value,
            from_currency: document.getElementById("fx_from").value,
            to_currency: document.getElementById("fx_to").value
          })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Conversion failed");
        result.textContent = `${data.converted_amount} ${data.to_currency} @ ${data.rate}`;
      } catch (error) {
        result.textContent = error.message;
      } finally {
        button.disabled = false;
        button.textContent = "Convert";
      }
    });

    function renderError(message) {
      setOverview({ planCount: 0, offerCount: 0, aggregateText: "current only", priceText: "-" });
      const results = document.getElementById("results");
      results.innerHTML = "";
      const errorBox = document.createElement("div");
      errorBox.className = "error";
      errorBox.textContent = message;
      results.appendChild(errorBox);
      document.getElementById("recommendations").innerHTML = "<div class='empty'>No data.</div>";
    }

    function renderStatus(data) {
      const parts = [];
      if (data.snapshot_id) parts.push(`snapshot ${data.snapshot_id}`);
      if (data.request) {
        parts.push(`${data.request.origin} -> ${data.request.destination}`);
      }
      if (data.aggregate) {
        const extra = data.aggregate.unconverted_offer_count
          ? `, ${data.aggregate.unconverted_offer_count} unconverted`
          : "";
        parts.push(
          `aggregated ${data.aggregate.offer_count} offers from ${data.aggregate.provider_count} sources${extra}`
        );
      }
      (data.warnings || []).forEach((warning) => parts.push(warning));
      if (!parts.length) return;
      const status = document.createElement("div");
      status.className = "empty";
      status.textContent = parts.join(" | ");
      document.getElementById("results").appendChild(status);
    }

    function renderTripPlan(data) {
      const options = data.options || [];
      const candidateCount = options.reduce((sum, option) => sum + (option.flight_offers || []).length, 0);
      const recommendedId = data.recommended_option ? data.recommended_option.option_id : null;
      const recommendedPrice = data.recommended_option
        ? planTotalText(data.recommended_option)
        : "-";
      setOverview({
        planCount: options.length,
        offerCount: candidateCount,
        aggregateText: recommendedId || "no recommendation",
        priceText: recommendedPrice
      });

      const results = document.getElementById("results");
      results.innerHTML = "";
      if (!options.length) {
        results.innerHTML = "<div class='empty'>No plans.</div>";
        document.getElementById("recommendations").innerHTML = "<div class='empty'>No data.</div>";
        return;
      }

      options.forEach((option) => {
        results.appendChild(planCard(option, option.option_id === recommendedId));
      });
      if (data.warnings && data.warnings.length) {
        const warning = document.createElement("div");
        warning.className = "empty";
        warning.textContent = data.warnings.join(" | ");
        results.appendChild(warning);
      }
      renderPlanRecommendation(data);
      updateRouteMap(data.recommended_option || options[0]);
    }

    function planCard(option, isRecommended) {
      const card = document.createElement("article");
      card.className = `plan-card${isRecommended ? " recommended" : ""}`;

      const main = document.createElement("div");
      main.className = "plan-card-main";
      const timeline = document.createElement("div");
      timeline.className = "timeline-pane";
      const meta = document.createElement("div");
      meta.className = "plan-meta";
      meta.appendChild(badge(statusLabel(option.price_status), `status-badge status-${option.price_status}`));
      meta.appendChild(badge(planKindLabel(option.kind), "kind-badge"));
      timeline.appendChild(meta);

      const title = document.createElement("h3");
      title.className = "plan-title";
      title.textContent = option.title;
      timeline.appendChild(title);

      const route = document.createElement("div");
      route.className = "hint";
      route.textContent = `${(option.flight_origin_airports || []).join("/")} -> ${(option.flight_destination_airports || []).join("/")}`;
      timeline.appendChild(route);
      timeline.appendChild(timelineList(option));

      const pricePane = document.createElement("div");
      pricePane.className = "price-pane";
      const priceTop = document.createElement("div");
      const priceLabel = document.createElement("div");
      priceLabel.className = "price-label";
      priceLabel.textContent = "Total price";
      const priceValue = document.createElement("div");
      priceValue.className = "price-value";
      priceValue.textContent = planTotalText(option);
      priceTop.appendChild(priceLabel);
      priceTop.appendChild(priceValue);
      priceTop.appendChild(priceBreakdown(option));
      pricePane.appendChild(priceTop);
      pricePane.appendChild(planActions(option));

      main.appendChild(timeline);
      main.appendChild(pricePane);
      card.appendChild(main);
      const details = providerDetails(option);
      if (details) card.appendChild(details);
      return card;
    }

    function timelineList(option) {
      const list = document.createElement("div");
      list.className = "timeline-list";
      (option.ground_legs || []).forEach((leg) => {
        list.appendChild(timelineItem({
          mode: leg.mode || "rail",
          title: `${leg.origin} -> ${leg.destination}`,
          subtitle: `${formatMinutes(leg.duration_minutes)} · ${leg.amount} ${leg.currency}`,
          detail: leg.notes || "Static MVP ground estimate"
        }));
      });
      list.appendChild(timelineItem(flightTimelineData(option)));
      if (option.price_status === "needs_manual_flight_price") {
        list.appendChild(timelineItem({
          mode: "manual",
          title: "Manual flight price needed",
          subtitle: "导入携程/飞猪页面报价或接入可定价 provider 后才能算总价",
          detail: "模板里的卡片内保存价格属于后续评估项。"
        }));
      }
      return list;
    }

    function flightTimelineData(option) {
      const offer = option.best_flight_offer;
      const segments = offer && offer.segments ? offer.segments : [];
      const first = segments[0] || {};
      const last = segments[segments.length - 1] || {};
      const carriers = segments.map((segment) => [segment.marketing_carrier, segment.flight_number].filter(Boolean).join("")).filter(Boolean);
      return {
        mode: "flight",
        title: `${text(first.origin || (option.flight_origin_airports || [])[0])} -> ${text(last.destination || (option.flight_destination_airports || [])[0])}`,
        subtitle: offer
          ? `${text(first.departure_time || first.departure_date)} - ${text(last.arrival_time || last.departure_date)} · ${formatMinutes(offer.travel_duration_minutes)}`
          : `${(option.flight_origin_airports || []).join("/")} -> ${(option.flight_destination_airports || []).join("/")}`,
        detail: offer
          ? `${offer.provider} · ${carriers.join(", ") || "carrier pending"}`
          : "No priced flight offer yet"
      };
    }

    function timelineItem(item) {
      const row = document.createElement("div");
      row.className = `timeline-item ${item.mode === "rail" ? "rail" : "flight"}`;
      const dot = document.createElement("div");
      dot.className = "timeline-dot";
      dot.textContent = item.mode === "rail" ? "R" : item.mode === "manual" ? "!" : "F";
      const copy = document.createElement("div");
      copy.className = "timeline-copy";
      const title = document.createElement("strong");
      title.textContent = item.title;
      const subtitle = document.createElement("span");
      subtitle.textContent = item.subtitle;
      const detail = document.createElement("small");
      detail.textContent = item.detail;
      copy.appendChild(title);
      copy.appendChild(subtitle);
      copy.appendChild(detail);
      row.appendChild(dot);
      row.appendChild(copy);
      return row;
    }

    function priceBreakdown(option) {
      const wrap = document.createElement("div");
      wrap.className = "breakdown";
      wrap.appendChild(breakdownRow("Flight fare", option.flight_amount ? `${option.flight_amount} ${option.flight_currency || option.currency}` : priceStatusHint(option.price_status)));
      wrap.appendChild(breakdownRow("Ground / rail", `${option.ground_amount || "0"} ${option.currency}`));
      wrap.appendChild(breakdownRow("Duration", formatMinutes(option.estimated_total_duration_minutes)));
      return wrap;
    }

    function breakdownRow(label, value) {
      const row = document.createElement("div");
      row.className = "breakdown-row";
      const left = document.createElement("span");
      left.textContent = label;
      const right = document.createElement("strong");
      right.textContent = text(value);
      row.appendChild(left);
      row.appendChild(right);
      return row;
    }

    function planActions(option) {
      const stack = document.createElement("div");
      stack.className = "action-stack";
      const book = document.createElement("button");
      book.className = "book-disabled";
      book.type = "button";
      book.disabled = true;
      book.textContent = "Book This Plan 后续评估";
      const details = document.createElement("button");
      details.className = "outline-action";
      details.type = "button";
      details.disabled = true;
      details.textContent = `${(option.verification_links || []).length} provider links below`;
      stack.appendChild(book);
      stack.appendChild(details);
      return stack;
    }

    function providerDetails(option) {
      const links = option.verification_links || [];
      const offers = option.flight_offers || [];
      if (!links.length && !offers.length) return null;
      const details = document.createElement("details");
      details.className = "provider-details";
      const summary = document.createElement("summary");
      summary.textContent = "Provider details and candidate flight offers";
      details.appendChild(summary);
      if (links.length) {
        const linkList = document.createElement("div");
        linkList.className = "link-list";
        links.slice(0, 6).forEach((item) => {
          const link = document.createElement("a");
          link.href = item.url;
          link.target = "_blank";
          link.rel = "noreferrer";
          link.textContent = item.provider;
          linkList.appendChild(link);
        });
        details.appendChild(linkList);
      }
      if (offers.length) {
        const grid = document.createElement("div");
        grid.className = "candidate-grid";
        offers.forEach((offer) => grid.appendChild(offerRow(option.title, offer)));
        details.appendChild(grid);
      }
      return details;
    }

    function offerRow(planTitle, offer) {
      const segments = offer.segments || [];
      const first = segments[0] || {};
      const last = segments[segments.length - 1] || {};
      const row = document.createElement("div");
      row.className = "candidate-row";
      [
        `${planTitle} · ${offer.provider}`,
        offerMoney(offer),
        `${text(first.departure_time || first.departure_date)} -> ${text(last.arrival_time || last.departure_date)}`,
        (offer.risk_flags || []).join(", ") || "risk not flagged"
      ].forEach((value) => {
        const cell = document.createElement("div");
        cell.textContent = value;
        row.appendChild(cell);
      });
      return row;
    }

    function renderPlanRecommendation(data) {
      const target = document.getElementById("recommendations");
      target.innerHTML = "";
      const summary = document.createElement("div");
      summary.className = "summary-text";
      summary.textContent = data.summary || "-";
      target.appendChild(summary);
      if (data.recommended_option) {
        target.appendChild(recommendationCard(
          "Recommended plan",
          data.recommended_option.title,
          planTotalText(data.recommended_option)
        ));
      }
      (data.options || []).forEach((option) => {
        if (!option.ground_legs || !option.ground_legs.length) return;
        const ground = option.ground_legs.map((leg) => `${leg.origin} to ${leg.destination}: ${leg.amount} ${leg.currency}`).join(" | ");
        target.appendChild(recommendationCard("Ground estimate", option.title, ground));
      });
    }

    function renderResults(data) {
      const offers = data.aggregate_offers && data.aggregate_offers.length ? data.aggregate_offers : data.offers;
      const currentCount = data.offers ? data.offers.length : offers.length;
      const aggregate = data.aggregate || {};
      const providerText = aggregate.provider_count ? `${aggregate.provider_count} sources` : "current only";
      setOverview({
        planCount: 0,
        offerCount: offers.length,
        aggregateText: providerText,
        priceText: offers[0] ? offerMoney(offers[0]) : "-"
      });
      const results = document.getElementById("results");
      results.innerHTML = "";
      if (!offers.length) {
        results.innerHTML = "<div class='empty'>No offers.</div>";
      } else {
        const heading = document.createElement("div");
        heading.className = "empty-state";
        heading.textContent = `Imported and aggregated offers: ${offers.length} (${currentCount} current)`;
        results.appendChild(heading);
        const grid = document.createElement("div");
        grid.className = "offer-grid";
        offers.forEach((offer) => grid.appendChild(importedOfferRow(offer)));
        results.appendChild(grid);
      }
      renderRecommendations(data.aggregate_recommendations || data.recommendations || {});
    }

    function importedOfferRow(offer) {
      const segments = offer.segments || [];
      const first = segments[0] || {};
      const last = segments[segments.length - 1] || {};
      const row = document.createElement("div");
      row.className = "offer-row";
      [
        `${offer.provider} · ${offer.source_market}`,
        offerMoney(offer),
        `${text(first.origin)} -> ${text(last.destination)} · ${formatMinutes(offer.travel_duration_minutes)}`,
        (offer.risk_flags || []).join(", ") || offer.ticketing_type || "risk not flagged"
      ].forEach((value) => {
        const cell = document.createElement("div");
        cell.textContent = value;
        row.appendChild(cell);
      });
      if (offer.booking_link) {
        const cell = document.createElement("div");
        const link = document.createElement("a");
        link.href = offer.booking_link;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = "Open provider";
        cell.appendChild(link);
        row.appendChild(cell);
      }
      return row;
    }

    function renderRecommendations(recommendations) {
      const target = document.getElementById("recommendations");
      target.innerHTML = "";
      const items = document.createDocumentFragment();
      const addOffer = (title, offer) => {
        if (!offer) return;
        items.appendChild(recommendationCard(title, offer.provider, offerMoney(offer)));
      };
      addOffer("Lowest price", recommendations.lowest_price);
      addOffer("Lowest risk", recommendations.lowest_risk);
      addOffer("Best value", recommendations.best_value);
      (recommendations.savings_vs_risk || []).slice(0, 3).forEach((item, index) => {
        items.appendChild(recommendationCard(`Savings ${index + 1}`, item.offer.provider, `${item.savings_amount} / ${item.risk_score}`));
      });
      if (items.childNodes.length) {
        target.appendChild(items);
      } else {
        target.innerHTML = "<div class='empty'>No data.</div>";
      }
    }

    function formatMinutes(minutes) {
      if (minutes === null || minutes === undefined) return "-";
      const hours = Math.floor(minutes / 60);
      const remainder = minutes % 60;
      if (hours && remainder) return `${hours}h${String(remainder).padStart(2, "0")}m`;
      if (hours) return `${hours}h`;
      return `${remainder}m`;
    }

    function setOverview({ planCount, offerCount, aggregateText, priceText }) {
      document.getElementById("offer-count").textContent = `${planCount} plans / ${offerCount} offers`;
      document.getElementById("summary-plan-count").textContent = String(planCount);
      document.getElementById("summary-offer-count").textContent = String(offerCount);
      document.getElementById("aggregate-count").textContent = aggregateText;
      document.getElementById("summary-price").textContent = priceText;
    }

    function badge(label, className) {
      const item = document.createElement("span");
      item.className = className;
      item.textContent = label;
      return item;
    }

    function planTotalText(option) {
      if (option.total_amount) return `${option.total_amount} ${option.currency}`;
      if (option.flight_amount) return `${option.flight_amount} ${option.flight_currency || option.currency}`;
      return priceStatusHint(option.price_status);
    }

    function offerMoney(offer) {
      const amount = offer.comparable_amount || offer.total_amount;
      return amount ? `${amount} ${offer.currency}` : "manual price";
    }

    function priceStatusHint(status) {
      const labels = {
        priced: "priced",
        needs_exchange_rate: "needs exchange rate",
        needs_manual_flight_price: "needs manual flight price",
        no_flights: "no flights"
      };
      return labels[status] || text(status);
    }

    function statusLabel(status) {
      return priceStatusHint(status).toUpperCase();
    }

    function planKindLabel(kind) {
      const labels = {
        flight_only: "Flight only",
        rail_flight: "Rail + flight",
        airport_stopover: "Airport stopover"
      };
      return labels[kind] || text(kind);
    }

    function updateRouteMap(option) {
      const routeCities = routeCitiesFromState(option);
      renderRouteMap(routeCities);
    }

    function routeCitiesFromState(option) {
      const cities = [];
      const pushCity = (value, role) => {
        const coordinates = cityCoordinates[value];
        if (!coordinates) return;
        if (cities.some((city) => city.value === value && city.role === role)) return;
        cities.push({ value, role, ...coordinates });
      };
      const origin = selectedOption("trip_origin_city");
      const destination = selectedOption("trip_destination_city");
      if (origin) pushCity(origin.value, "origin");
      const connectionType = document.getElementById("trip_connection_type").value;
      const connection = selectedOption("trip_connection_city");
      if (connection && connection.value && connectionType !== "none") {
        pushCity(connection.value, connectionType === "rail" ? "rail" : "connection");
      }
      if (destination) pushCity(destination.value, "destination");
      (option?.ground_legs || []).forEach((leg) => {
        pushCity(cityValueFromLeg(leg.origin), "rail");
        pushCity(cityValueFromLeg(leg.destination), "rail");
      });
      return cities;
    }

    function cityValueFromLeg(label) {
      const normalized = String(label || "").toLowerCase();
      return Object.keys(cityCoordinates).find((city) => normalized.includes(city.toLowerCase())) || label;
    }

    function renderRouteMap(cities) {
      const target = document.getElementById("route-map");
      const legend = document.getElementById("route-map-legend");
      const scope = routeScope(cities);
      document.getElementById("route-map-scope").textContent = scope.label;
      target.innerHTML = "";
      legend.innerHTML = "";
      const svg = svgElement("svg", { viewBox: "0 0 100 64", role: "img" });
      const defs = svgElement("defs");
      const gradient = svgElement("linearGradient", { id: "routeSea", x1: "0", y1: "0", x2: "1", y2: "1" });
      gradient.appendChild(svgElement("stop", { offset: "0%", "stop-color": "#d8edf8" }));
      gradient.appendChild(svgElement("stop", { offset: "100%", "stop-color": "#f7fbff" }));
      defs.appendChild(gradient);
      svg.appendChild(defs);
      svg.appendChild(svgElement("rect", { width: "100", height: "64", rx: "6", fill: "url(#routeSea)" }));
      drawGrid(svg);
      drawLandHints(svg, scope);
      const points = cities.map((city) => ({ ...city, ...projectCity(city, scope) }));
      for (let index = 0; index < points.length - 1; index += 1) {
        const from = points[index];
        const to = points[index + 1];
        const path = svgElement("path", {
          class: `map-route ${to.role === "rail" || from.role === "rail" ? "map-rail" : ""}`,
          d: curvedPath(from, to)
        });
        svg.appendChild(path);
      }
      points.forEach((point, index) => {
        svg.appendChild(svgElement("circle", {
          class: `map-point ${point.role === "rail" || point.role === "connection" ? "connection" : ""}`,
          cx: point.x,
          cy: point.y,
          r: "3.1"
        }));
        const number = svgElement("text", {
          class: "map-marker-number",
          x: point.x,
          y: point.y
        });
        number.textContent = String(index + 1);
        svg.appendChild(number);
        const item = document.createElement("span");
        item.textContent = `${index + 1}. ${point.label}`;
        legend.appendChild(item);
      });
      target.appendChild(svg);
    }

    function routeScope(cities) {
      if (!cities.length) {
        return {
          label: "请选择城市以显示路线范围。",
          minLon: 95,
          maxLon: 130,
          minLat: 18,
          maxLat: 42,
          region: "east-asia"
        };
      }
      const lons = cities.map((city) => city.lon);
      const lats = cities.map((city) => city.lat);
      let minLon = Math.min(...lons);
      let maxLon = Math.max(...lons);
      let minLat = Math.min(...lats);
      let maxLat = Math.max(...lats);
      const lonSpan = maxLon - minLon;
      const latSpan = maxLat - minLat;
      if (lonSpan > 80) {
        return {
          label: "全球视野：跨洲航线自动拉远。",
          minLon: -170,
          maxLon: 150,
          minLat: -10,
          maxLat: 65,
          region: "global"
        };
      }
      const paddingLon = Math.max(6, lonSpan * 0.75);
      const paddingLat = Math.max(4, latSpan * 0.9);
      minLon -= paddingLon;
      maxLon += paddingLon;
      minLat -= paddingLat;
      maxLat += paddingLat;
      const eastAsia = minLon >= 95 && maxLon <= 135 && minLat >= 15 && maxLat <= 45;
      return {
        label: eastAsia ? "东亚视野：适合中国大陆、港澳台和周边航线。" : "区域视野：按当前城市自动缩放。",
        minLon,
        maxLon,
        minLat,
        maxLat,
        region: eastAsia ? "east-asia" : "regional"
      };
    }

    function projectCity(city, scope) {
      const x = 8 + ((city.lon - scope.minLon) / (scope.maxLon - scope.minLon || 1)) * 84;
      const y = 56 - ((city.lat - scope.minLat) / (scope.maxLat - scope.minLat || 1)) * 48;
      return {
        x: Number(Math.max(6, Math.min(94, x)).toFixed(2)),
        y: Number(Math.max(6, Math.min(58, y)).toFixed(2))
      };
    }

    function curvedPath(from, to) {
      const midX = (from.x + to.x) / 2;
      const midY = Math.min(from.y, to.y) - Math.max(7, Math.abs(from.x - to.x) * 0.08);
      return `M ${from.x} ${from.y} Q ${midX.toFixed(2)} ${midY.toFixed(2)} ${to.x} ${to.y}`;
    }

    function drawGrid(svg) {
      [20, 40, 60, 80].forEach((x) => svg.appendChild(svgElement("line", { class: "map-grid", x1: x, y1: "0", x2: x, y2: "64" })));
      [16, 32, 48].forEach((y) => svg.appendChild(svgElement("line", { class: "map-grid", x1: "0", y1: y, x2: "100", y2: y })));
    }

    function drawLandHints(svg, scope) {
      const land = scope.region === "global"
        ? [
            "M4,24 C14,10 27,11 36,25 C28,34 18,35 4,24 Z",
            "M55,18 C68,5 90,11 98,30 C87,39 67,35 55,18 Z",
            "M66,39 C79,35 93,43 97,58 L66,58 Z"
          ]
        : [
            "M9,14 C25,2 45,8 53,23 C39,32 20,30 9,14 Z",
            "M54,16 C72,7 92,18 96,38 C79,47 62,38 54,16 Z",
            "M47,45 C57,38 70,43 76,57 L47,57 Z"
          ];
      land.forEach((d) => svg.appendChild(svgElement("path", { d, fill: "rgba(255,255,255,0.72)", stroke: "rgba(0,32,69,0.08)", "stroke-width": "0.5" })));
    }

    function svgElement(name, attributes = {}) {
      const element = document.createElementNS("http://www.w3.org/2000/svg", name);
      Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
      return element;
    }

    function recommendationCard(title, left, right) {
      const card = document.createElement("div");
      card.className = "rec";
      const heading = document.createElement("div");
      heading.className = "rec-title";
      heading.textContent = title;
      const main = document.createElement("div");
      main.className = "rec-main";
      const leftSpan = document.createElement("span");
      leftSpan.textContent = text(left);
      const rightSpan = document.createElement("span");
      rightSpan.textContent = text(right);
      main.appendChild(leftSpan);
      main.appendChild(rightSpan);
      card.appendChild(heading);
      card.appendChild(main);
      return card;
    }

    init().catch((error) => {
      const results = document.getElementById("results");
      results.innerHTML = "";
      const errorBox = document.createElement("div");
      errorBox.className = "error";
      errorBox.textContent = error.message;
      results.appendChild(errorBox);
    });
  </script>
</body>
</html>"""
