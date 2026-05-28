"""FastAPI REST service and local Web UI."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from reverse_flight_tickets import __version__
from reverse_flight_tickets.config import AppConfig
from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.providers import (
    ProviderContext,
    available_provider_metadata,
    providers_from_names,
)
from reverse_flight_tickets.search import SearchOrchestrator
from reverse_flight_tickets.search.filters import normalize_carrier_codes
from reverse_flight_tickets.storage import SearchSnapshot, SqliteSearchRepository

DEFAULT_EXCLUDED_CARRIERS = ("ZZ",)


class SearchApiRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    db_url: str | None = None


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
    orchestrator = SearchOrchestrator(
        providers_to_query,
        timeout_seconds=config.provider_timeout_seconds,
        excluded_carriers=_excluded_carriers(payload),
        exchange_rates=dict(config.exchange_rates),
        payment_fee_rate=config.payment_fee_rate,
        baggage_fee_amount=config.baggage_fee_amount,
    )
    result = await orchestrator.search(request, context)
    snapshot_id: str | None = None
    if payload.save_snapshot:
        repository = SqliteSearchRepository(payload.db_url or config.database_url)
        snapshot_id = repository.save_search_snapshot(SearchSnapshot.from_search_result(result))

    response = result.to_dict()
    response["snapshot_id"] = snapshot_id
    return response


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
      gap: 14px;
      padding: 18px;
      border: 1px solid var(--line);
      background: var(--panel);
    }

    label {
      display: grid;
      gap: 6px;
      font-size: 12px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
    }

    input,
    select {
      min-height: 40px;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      font: inherit;
      color: var(--ink);
      background: #ffffff;
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

    .toolbar {
      display: flex;
      justify-content: flex-end;
      align-items: end;
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
    <form id="search-form">
      <label class="span-2">Origin
        <input id="origin" autocomplete="off" value="PVG" required>
      </label>
      <label class="span-2">Destination
        <input id="destination" autocomplete="off" value="LAX" required>
      </label>
      <label class="span-2">Departure
        <input id="departure_date" type="date" value="2026-10-01" required>
      </label>
      <label class="span-2">Return
        <input id="return_date" type="date">
      </label>
      <label class="span-2">Passengers
        <input id="passenger_count" type="number" min="1" value="1">
      </label>
      <label class="span-2">Cabin
        <select id="cabin">
          <option value="economy">Economy</option>
          <option value="premium_economy">Premium economy</option>
          <option value="business">Business</option>
          <option value="first">First</option>
        </select>
      </label>
      <label class="span-3">Markets
        <input id="allowed_markets" value="US">
      </label>
      <label class="span-3">Currencies
        <input id="allowed_currencies" value="USD">
      </label>
      <label class="span-3">Stopovers
        <input id="stopovers" placeholder="HND,ICN">
      </label>
      <label class="span-3">Date window
        <input id="date_flexibility_days" type="number" min="0" value="0">
      </label>
      <div class="span-12 providers" id="providers"></div>
      <div class="span-9 toggles">
        <label class="choice"><input id="include_research" type="checkbox">Research</label>
        <label class="choice"><input id="include_split_ticket" type="checkbox">Split ticket</label>
        <label class="choice"><input id="include_self_transfer" type="checkbox">Self transfer</label>
        <label class="choice"><input id="include_test_carriers" type="checkbox">Test carriers</label>
        <label class="choice"><input id="save_snapshot" type="checkbox">Snapshot</label>
      </div>
      <div class="span-3 toolbar">
        <button id="search-button" type="submit">Search</button>
      </div>
    </form>
    <div class="layout">
      <section>
        <div class="section-title">
          <span>Offers</span>
          <span class="status" id="offer-count">0</span>
        </div>
        <div class="table-wrap" id="results"><div class="empty">No offers.</div></div>
      </section>
      <section>
        <div class="section-title">Recommendations</div>
        <div class="recommendations" id="recommendations"><div class="empty">No data.</div></div>
      </section>
    </div>
  </main>
  <script>
    const state = { providers: [] };

    const csv = (value) => value.split(",").map((part) => part.trim()).filter(Boolean);
    const text = (value) => value === null || value === undefined || value === "" ? "-" : String(value);

    async function init() {
      const [health, providers] = await Promise.all([
        fetch("/health").then((response) => response.json()),
        fetch("/api/providers").then((response) => response.json())
      ]);
      document.getElementById("health").textContent = `${health.status} ${health.version}`;
      state.providers = providers.providers;
      renderProviders();
    }

    function renderProviders() {
      const target = document.getElementById("providers");
      target.innerHTML = "";
      state.providers.forEach((provider) => {
        if (provider.research) return;
        const label = document.createElement("label");
        label.className = "choice";
        label.innerHTML = `<input type="checkbox" name="provider" value="${provider.name}" ${provider.default_enabled ? "checked" : ""}>${provider.name}`;
        target.appendChild(label);
      });
    }

    document.getElementById("search-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = document.getElementById("search-button");
      button.disabled = true;
      button.textContent = "Searching";
      try {
        const provider_names = Array.from(document.querySelectorAll("input[name='provider']:checked")).map((input) => input.value);
        const payload = {
          origin: document.getElementById("origin").value,
          destination: document.getElementById("destination").value,
          departure_date: document.getElementById("departure_date").value,
          return_date: document.getElementById("return_date").value || null,
          passenger_count: Number(document.getElementById("passenger_count").value || 1),
          cabin: document.getElementById("cabin").value,
          allowed_markets: csv(document.getElementById("allowed_markets").value),
          allowed_currencies: csv(document.getElementById("allowed_currencies").value),
          stopovers: csv(document.getElementById("stopovers").value),
          date_flexibility_days: Number(document.getElementById("date_flexibility_days").value || 0),
          provider_names,
          include_research: document.getElementById("include_research").checked,
          include_split_ticket: document.getElementById("include_split_ticket").checked,
          include_self_transfer: document.getElementById("include_self_transfer").checked,
          include_test_carriers: document.getElementById("include_test_carriers").checked,
          save_snapshot: document.getElementById("save_snapshot").checked
        };
        const response = await fetch("/api/search", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Search failed");
        renderResults(data);
      } catch (error) {
        document.getElementById("results").innerHTML = `<div class="error">${error.message}</div>`;
      } finally {
        button.disabled = false;
        button.textContent = "Search";
      }
    });

    function renderResults(data) {
      document.getElementById("offer-count").textContent = `${data.offers.length}`;
      if (!data.offers.length) {
        document.getElementById("results").innerHTML = "<div class='empty'>No offers.</div>";
      } else {
        const rows = data.offers.map((offer) => {
          const segments = offer.segments || [];
          const first = segments[0] || {};
          const last = segments[segments.length - 1] || {};
          const risks = (offer.risk_flags || []).join(", ") || "-";
          const link = offer.booking_link ? `<a href="${offer.booking_link}" target="_blank" rel="noreferrer">Open</a>` : "-";
          return `<tr>
            <td>${offer.provider}</td>
            <td>${offer.source_market}</td>
            <td>${offer.currency}</td>
            <td>${text(offer.comparable_amount || offer.total_amount || "manual")}</td>
            <td>${segments.map((segment) => segment.marketing_carrier || "").filter(Boolean).join(", ") || "-"}</td>
            <td>${text(first.departure_time || first.departure_date)}</td>
            <td>${text(last.arrival_time || last.departure_date)}</td>
            <td>${offer.ticketing_type}</td>
            <td>${risks}</td>
            <td>${link}</td>
          </tr>`;
        }).join("");
        document.getElementById("results").innerHTML = `<table>
          <thead><tr><th>Provider</th><th>Market</th><th>Currency</th><th>Amount</th><th>Airlines</th><th>Depart</th><th>Arrive</th><th>Ticketing</th><th>Risks</th><th>Link</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>`;
      }
      renderRecommendations(data.recommendations || {});
    }

    function renderRecommendations(recommendations) {
      const target = document.getElementById("recommendations");
      const items = [];
      const addOffer = (title, offer) => {
        if (!offer) return;
        items.push(`<div class="rec"><div class="rec-title">${title}</div><div class="rec-main"><span>${offer.provider}</span><span>${text(offer.comparable_amount || offer.total_amount || "manual")} ${offer.currency}</span></div></div>`);
      };
      addOffer("Lowest price", recommendations.lowest_price);
      addOffer("Lowest risk", recommendations.lowest_risk);
      addOffer("Best value", recommendations.best_value);
      (recommendations.savings_vs_risk || []).slice(0, 3).forEach((item, index) => {
        items.push(`<div class="rec"><div class="rec-title">Savings ${index + 1}</div><div class="rec-main"><span>${item.offer.provider}</span><span>${item.savings_amount} / <span class="risk">${item.risk_score}</span></span></div></div>`);
      });
      target.innerHTML = items.length ? items.join("") : "<div class='empty'>No data.</div>";
    }

    init().catch((error) => {
      document.getElementById("health").textContent = "offline";
      document.getElementById("results").innerHTML = `<div class="error">${error.message}</div>`;
    });
  </script>
</body>
</html>"""
