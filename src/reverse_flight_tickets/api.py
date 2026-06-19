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
  </style>
</head>
<body>
  <header>
    <h1>ReverseFlightTickets</h1>
    <div class="status" id="health">checking</div>
  </header>
  <main>
    <form id="trip-plan-form">
      <div class="subhead">
        <span>Trip Plan</span>
        <span class="hint">Compare direct city flights with optional rail or airport connections.</span>
      </div>
      <div class="field trip-route-field" data-option-picker="trip_origin_city">
        <div class="field-label">From</div>
        <div class="option-picker"></div>
      </div>
      <div class="field trip-route-field" data-option-picker="trip_destination_city">
        <div class="field-label">To</div>
        <div class="option-picker"></div>
      </div>
      <label class="trip-date-field">Departure
        <input id="trip_departure_date" type="date" required>
      </label>
      <label class="trip-date-field">Return
        <input id="trip_return_date" type="date" required>
      </label>
      <label class="trip-small-field">Passengers
        <input id="trip_passenger_count" type="number" min="1" value="1">
      </label>
      <label class="trip-small-field">Cabin
        <select id="trip_cabin">
          <option value="economy">Economy</option>
          <option value="premium_economy">Premium economy</option>
          <option value="business">Business</option>
          <option value="first">First</option>
        </select>
      </label>
      <div class="field trip-control-field" data-option-picker="trip_source_market">
        <div class="field-label">Market</div>
        <div class="option-picker"></div>
      </div>
      <div class="field trip-control-field" data-option-picker="trip_target_currency">
        <div class="field-label">Currency</div>
        <div class="option-picker"></div>
      </div>
      <label class="trip-control-field">Connection type
        <select id="trip_connection_type">
          <option value="rail">Rail to another airport city</option>
          <option value="none">Direct city airports only</option>
          <option value="airport">Airport stopover</option>
        </select>
      </label>
      <div class="field trip-control-field" data-option-picker="trip_connection_city">
        <div class="field-label">Connection city</div>
        <div class="option-picker"></div>
      </div>
      <label class="trip-filter-field">Flight filter
        <select id="trip_flight_filter">
          <option value="all">All flight options</option>
          <option value="direct">Direct flights only</option>
          <option value="via_city">Only via selected city</option>
        </select>
      </label>
      <div class="field trip-filter-field" data-option-picker="trip_flight_stopover_city">
        <div class="field-label">Via city</div>
        <div class="option-picker"></div>
      </div>
      <label class="span-3">Manual rates
        <input id="trip_manual_exchange_rates" placeholder="USD:CNY=7.20">
      </label>
      <div class="span-9 trip-actions">
        <div class="providers" id="trip_providers"></div>
        <label class="choice"><input id="trip_include_test_carriers" type="checkbox">Test carriers</label>
      </div>
      <div class="span-3 toolbar">
        <button id="trip-plan-button" type="submit">Compare plans</button>
      </div>
    </form>
    <form id="browser-import-form" class="import-panel">
      <div class="subhead">
        <span>Import Browser Offers</span>
        <span class="hint">Paste or load the JSON/CSV exported by the userscript.</span>
      </div>
      <label class="span-6">Export file
        <input id="browser_file" type="file" accept=".json,.csv,application/json,text/csv">
      </label>
      <label class="span-3">Target currency
        <input id="browser_target_currency" placeholder="CNY">
      </label>
      <div class="span-3 toggles">
        <label class="choice"><input id="browser_save_snapshot" type="checkbox" checked>Snapshot</label>
      </div>
      <label class="span-12">Export content
        <textarea id="browser_content" placeholder="Paste userscript JSON or CSV here"></textarea>
      </label>
      <div class="span-12 toolbar">
        <button class="secondary" id="clear-browser-import" type="button">Clear</button>
        <button id="browser-import-button" type="submit">Import offers</button>
      </div>
    </form>
    <form id="currency-form" class="utility-panel">
      <div class="subhead">
        <span>Currency Tool</span>
        <span class="hint">Uses the configured static rates or exchange-rate provider.</span>
      </div>
      <label class="span-3">Amount
        <input id="fx_amount" inputmode="decimal" value="1000">
      </label>
      <label class="span-2">From
        <input id="fx_from" value="CNY">
      </label>
      <label class="span-2">To
        <input id="fx_to" value="USD">
      </label>
      <div class="span-2 toolbar">
        <button id="fx-button" type="submit">Convert</button>
      </div>
      <div class="span-3 status" id="fx_result">-</div>
    </form>
    <div class="layout">
      <section>
        <div class="section-title">
          <span>Plans and offers</span>
          <span class="status" id="offer-count">0</span>
        </div>
        <div class="table-wrap" id="results"><div class="empty">No offers.</div></div>
      </section>
      <section>
        <div class="section-title">
          <span>Recommendations</span>
          <span class="status" id="aggregate-count">current only</span>
        </div>
        <div class="recommendations" id="recommendations"><div class="empty">No data.</div></div>
      </section>
    </div>
  </main>
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

    async function init() {
      const [health, providers, metadata] = await Promise.all([
        fetch("/health").then((response) => response.json()),
        fetch("/api/providers").then((response) => response.json()),
        fetch("/api/trip-plan/metadata").then((response) => response.json())
      ]);
      document.getElementById("health").textContent = `${health.status} ${health.version}`;
      state.providers = providers.providers;
      state.tripMetadata = metadata;
      hydrateTripOptionConfigs(metadata);
      setupOptionPickers();
      renderProviders();
      setupTripPlanDependencies();
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
      });
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
        button.textContent = "Compare plans";
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
      document.getElementById("offer-count").textContent = "0";
      document.getElementById("aggregate-count").textContent = "current only";
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
      document.getElementById("offer-count").textContent = `${options.length} plans / ${candidateCount} offers`;
      document.getElementById("aggregate-count").textContent = data.recommended_option ? data.recommended_option.option_id : "no recommendation";
      if (!options.length) {
        document.getElementById("results").innerHTML = "<div class='empty'>No plans.</div>";
        document.getElementById("recommendations").innerHTML = "<div class='empty'>No data.</div>";
        return;
      }
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const headerRow = document.createElement("tr");
      ["Plan", "Total", "Flight", "Ground", "Status", "Airports", "Best source", "Duration", "Links"].forEach((label) => {
        const th = document.createElement("th");
        th.textContent = label;
        headerRow.appendChild(th);
      });
      thead.appendChild(headerRow);
      const tbody = document.createElement("tbody");
      options.forEach((option) => {
        const row = document.createElement("tr");
        const airports = `${option.flight_origin_airports.join("/")} -> ${option.flight_destination_airports.join("/")}`;
        const bestSource = option.best_flight_offer ? option.best_flight_offer.provider : "-";
        const values = [
          option.title,
          option.total_amount ? `${option.total_amount} ${option.currency}` : "-",
          option.flight_amount ? `${option.flight_amount} ${option.flight_currency || option.currency}` : "-",
          `${option.ground_amount} ${option.currency}`,
          option.price_status,
          airports,
          bestSource,
          formatMinutes(option.estimated_total_duration_minutes)
        ];
        values.forEach((value) => {
          const td = document.createElement("td");
          td.textContent = text(value);
          row.appendChild(td);
        });
        const linkCell = document.createElement("td");
        const links = document.createElement("div");
        links.className = "link-list";
        (option.verification_links || []).slice(0, 4).forEach((item) => {
          const link = document.createElement("a");
          link.href = item.url;
          link.target = "_blank";
          link.rel = "noreferrer";
          link.textContent = item.provider;
          links.appendChild(link);
        });
        linkCell.appendChild(links.childNodes.length ? links : document.createTextNode("-"));
        row.appendChild(linkCell);
        tbody.appendChild(row);
      });
      table.appendChild(thead);
      table.appendChild(tbody);
      const results = document.getElementById("results");
      results.innerHTML = "";
      results.appendChild(table);
      const candidateTable = tripPlanCandidateTable(options);
      if (candidateTable) {
        const heading = document.createElement("div");
        heading.className = "section-title";
        heading.textContent = "Candidate flight offers";
        results.appendChild(heading);
        results.appendChild(candidateTable);
      }
      if (data.warnings && data.warnings.length) {
        const warning = document.createElement("div");
        warning.className = "empty";
        warning.textContent = data.warnings.join(" | ");
        results.appendChild(warning);
      }
      renderPlanRecommendation(data);
    }

    function tripPlanCandidateTable(options) {
      const rows = [];
      options.forEach((option) => {
        (option.flight_offers || []).forEach((offer) => {
          rows.push({ option, offer });
        });
      });
      if (!rows.length) return null;
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const headerRow = document.createElement("tr");
      ["Plan", "Provider", "Amount", "Airlines", "Depart", "Arrive", "Duration", "Risks"].forEach((label) => {
        const th = document.createElement("th");
        th.textContent = label;
        headerRow.appendChild(th);
      });
      thead.appendChild(headerRow);
      const tbody = document.createElement("tbody");
      rows.forEach(({ option, offer }) => {
        const segments = offer.segments || [];
        const first = segments[0] || {};
        const last = segments[segments.length - 1] || {};
        const amount = offer.comparable_amount || offer.total_amount;
        const values = [
          option.title,
          offer.provider,
          amount ? `${amount} ${offer.currency}` : "manual",
          segments.map((segment) => segment.marketing_carrier || "").filter(Boolean).join(", ") || "-",
          text(first.departure_time || first.departure_date),
          text(last.arrival_time || last.departure_date),
          formatMinutes(offer.travel_duration_minutes),
          (offer.risk_flags || []).join(", ") || "-"
        ];
        const row = document.createElement("tr");
        values.forEach((value) => {
          const td = document.createElement("td");
          td.textContent = text(value);
          row.appendChild(td);
        });
        tbody.appendChild(row);
      });
      table.appendChild(thead);
      table.appendChild(tbody);
      return table;
    }

    function renderPlanRecommendation(data) {
      const target = document.getElementById("recommendations");
      target.innerHTML = "";
      const summary = document.createElement("div");
      summary.className = "summary-text";
      summary.textContent = data.summary || "-";
      target.appendChild(summary);
      if (data.recommended_option) {
        const option = data.recommended_option;
        const amount = option.total_amount
          ? `${option.total_amount} ${option.currency}`
          : option.flight_amount
            ? `${option.flight_amount} ${option.flight_currency || option.currency} / ${option.price_status}`
            : option.price_status;
        target.appendChild(recommendationCard("Recommended plan", option.title, amount));
      }
      (data.options || []).forEach((option) => {
        if (!option.ground_legs || !option.ground_legs.length) return;
        const ground = option.ground_legs.map((leg) => `${leg.origin} to ${leg.destination}: ${leg.amount} ${leg.currency}`).join(" | ");
        target.appendChild(recommendationCard("Ground estimate", option.title, ground));
      });
    }

    function renderResults(data) {
      const offers = data.aggregate_offers && data.aggregate_offers.length ? data.aggregate_offers : data.offers;
      const aggregate = data.aggregate || {};
      const providerText = aggregate.provider_count ? `${aggregate.provider_count} sources` : "current only";
      document.getElementById("offer-count").textContent = `${offers.length} (${data.offers.length} current)`;
      document.getElementById("aggregate-count").textContent = providerText;
      if (!offers.length) {
        document.getElementById("results").innerHTML = "<div class='empty'>No offers.</div>";
      } else {
        const table = document.createElement("table");
        const thead = document.createElement("thead");
        const headerRow = document.createElement("tr");
        ["Provider", "Market", "Currency", "Amount", "Airlines", "Depart", "Arrive", "Ticketing", "Risks", "Link"].forEach((label) => {
          const th = document.createElement("th");
          th.textContent = label;
          headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        const tbody = document.createElement("tbody");
        offers.forEach((offer) => {
          const segments = offer.segments || [];
          const first = segments[0] || {};
          const last = segments[segments.length - 1] || {};
          const values = [
            offer.provider,
            offer.source_market,
            offer.currency,
            text(offer.comparable_amount || offer.total_amount || "manual"),
            segments.map((segment) => segment.marketing_carrier || "").filter(Boolean).join(", ") || "-",
            text(first.departure_time || first.departure_date),
            text(last.arrival_time || last.departure_date),
            offer.ticketing_type,
            (offer.risk_flags || []).join(", ") || "-"
          ];
          const row = document.createElement("tr");
          values.forEach((value) => {
            const td = document.createElement("td");
            td.textContent = text(value);
            row.appendChild(td);
          });
          const linkCell = document.createElement("td");
          if (offer.booking_link) {
            const link = document.createElement("a");
            link.href = offer.booking_link;
            link.target = "_blank";
            link.rel = "noreferrer";
            link.textContent = "Open";
            linkCell.appendChild(link);
          } else {
            linkCell.textContent = "-";
          }
          row.appendChild(linkCell);
          tbody.appendChild(row);
        });
        table.appendChild(thead);
        table.appendChild(tbody);
        const results = document.getElementById("results");
        results.innerHTML = "";
        results.appendChild(table);
      }
      renderRecommendations(data.aggregate_recommendations || data.recommendations || {});
    }

    function renderRecommendations(recommendations) {
      const target = document.getElementById("recommendations");
      target.innerHTML = "";
      const items = document.createDocumentFragment();
      const addOffer = (title, offer) => {
        if (!offer) return;
        items.appendChild(recommendationCard(title, offer.provider, `${text(offer.comparable_amount || offer.total_amount || "manual")} ${offer.currency}`));
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
      document.getElementById("health").textContent = "offline";
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
