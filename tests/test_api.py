from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from reverse_flight_tickets import api
from reverse_flight_tickets.api import app
from tests.test_trip_planner import RoutePriceProvider


def test_api_health() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_web_ui_uses_searchable_option_lists_for_trip_plan_fields() -> None:
    client = TestClient(app)

    response = client.get("/")
    html = response.text

    assert response.status_code == 200
    assert 'data-option-picker="trip_origin_city"' in html
    assert 'data-option-picker="trip_destination_city"' in html
    assert 'data-option-picker="trip_source_market"' in html
    assert 'data-option-picker="trip_target_currency"' in html
    assert 'data-option-picker="trip_connection_city"' in html
    assert 'data-option-picker="trip_flight_stopover_city"' in html
    assert 'id="trip_connection_type"' in html
    assert 'id="trip_flight_filter"' in html
    assert 'id="trip_origin_city_search"' not in html
    assert '<input id="trip_origin_city" autocomplete="off"' not in html
    assert "Type to filter" in html
    assert "No matching option. All supported options are shown below." in html
    assert '.option-picker[data-open="true"] .option-list' in html
    assert "China mainland" not in html


def test_api_trip_plan_metadata_returns_city_market_and_rail_options() -> None:
    client = TestClient(app)

    response = client.get(
        "/api/trip-plan/metadata",
        params={"origin_city": "Nanjing", "destination_city": "Taipei"},
    )

    data = response.json()
    assert response.status_code == 200
    assert {"Nanjing", "Beijing", "Hong Kong", "Macau"} <= {
        city["value"] for city in data["cities"]
    }
    assert data["rail_connection_options"][0]["value"] == "Shanghai"
    assert [market["label"] for market in data["markets"][:4]] == [
        "中国大陆",
        "中国香港",
        "中国澳门",
        "中国台湾",
    ]


def test_api_search_returns_manual_offer() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/search",
        json={
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "provider_names": ["skyscanner"],
        },
    )

    data = response.json()
    assert response.status_code == 200
    assert data["offers"][0]["provider"] == "skyscanner"
    assert data["offers"][0]["manual_check_required"] is True


def test_api_search_rejects_unknown_provider() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/search",
        json={
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "provider_names": ["missing"],
        },
    )

    assert response.status_code == 400


def test_api_search_rejects_extra_fields() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/search",
        json={
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "db_url": "sqlite:///unexpected.sqlite3",
        },
    )

    assert response.status_code == 422


def test_api_search_snapshot_uses_configured_database(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "api.sqlite3"
    monkeypatch.setattr(
        api.AppConfig,
        "from_env",
        classmethod(lambda cls: cls(database_url=f"sqlite:///{database_path}")),
    )
    client = TestClient(app)

    response = client.post(
        "/api/search",
        json={
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
            "provider_names": ["skyscanner"],
            "save_snapshot": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["snapshot_id"]
    assert database_path.exists()


def test_api_import_browser_export_returns_ranked_offers() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/import-browser",
        json={
            "filename": "ctrip.json",
            "content": """
            {
              "schema_version": "rft-browser-offers/v1",
              "source": "ctrip",
              "request": {
                "origin": "SHA",
                "destination": "TPE",
                "departure_date": "2026-05-30",
                "allowed_markets": ["CN"],
                "allowed_currencies": ["CNY"]
              },
              "offers": [
                {
                  "provider": "ctrip",
                  "amount": "1600",
                  "currency": "CNY",
                  "flight_numbers": ["MU5001"],
                  "departure_time": "08:00",
                  "arrival_time": "10:00",
                  "link": "https://example.test/high"
                },
                {
                  "provider": "ctrip",
                  "amount": "900",
                  "currency": "CNY",
                  "flight_numbers": ["CI502"],
                  "departure_time": "12:00",
                  "arrival_time": "14:00",
                  "link": "https://example.test/low"
                }
              ]
            }
            """,
        },
    )

    data = response.json()
    assert response.status_code == 200
    assert data["snapshot_id"] is None
    assert data["offers"][0]["total_amount"] == "900"
    assert data["offers"][0]["provider"] == "ctrip-browser"
    assert data["offers"][0]["manual_check_required"] is True


def test_api_import_browser_export_snapshot_uses_configured_database(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "browser-api.sqlite3"
    monkeypatch.setattr(
        api.AppConfig,
        "from_env",
        classmethod(lambda cls: cls(database_url=f"sqlite:///{database_path}")),
    )
    client = TestClient(app)

    response = client.post(
        "/api/import-browser",
        json={
            "filename": "browser.csv",
            "save_snapshot": True,
            "content": (
                "schema_version,source,provider,page_url,origin,destination,departure_date,"
                "currency,amount,airline,flight_numbers,departure_time,arrival_time,stops,link\n"
                "rft-browser-offers/v1,fliggy,fliggy,https://example.test,DLC,TPE,"
                "2026-05-29,CNY,888,中国国航,CA1234,09:30,15:20,direct,"
                "https://example.test/book\n"
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["snapshot_id"]
    assert database_path.exists()


def test_api_currency_convert_uses_configured_rates(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fx-api.sqlite3"
    monkeypatch.setattr(
        api.AppConfig,
        "from_env",
        classmethod(
            lambda cls: cls(
                database_url=f"sqlite:///{database_path}",
                exchange_rates={("CNY", "USD"): Decimal("0.14")},
            )
        ),
    )
    client = TestClient(app)

    response = client.post(
        "/api/currency/convert",
        json={"amount": "2225", "from_currency": "CNY", "to_currency": "USD"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "amount": "2225",
        "from_currency": "CNY",
        "to_currency": "USD",
        "converted_amount": "311.50",
        "rate": "0.140000",
    }


def test_api_trip_plan_returns_nanjing_taipei_options(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "trip-plan-api.sqlite3"
    monkeypatch.setattr(
        api.AppConfig,
        "from_env",
        classmethod(lambda cls: cls(database_url=f"sqlite:///{database_path}")),
    )
    client = TestClient(app)

    response = client.post(
        "/api/trip-plan",
        json={
            "departure_date": "2026-07-01",
            "return_date": "2026-07-08",
            "provider_names": ["skyscanner"],
        },
    )

    data = response.json()
    assert response.status_code == 200
    assert {option["option_id"] for option in data["options"]} == {
        "nanjing-flight",
        "shanghai-rail-flight",
    }
    assert all(option["flight_offers"] for option in data["options"])
    assert data["summary"].startswith("Need priced flight offers")
    assert data["recommended_option"]["option_id"] == "nanjing-flight"


def test_api_trip_plan_accepts_manual_exchange_rate(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "trip-plan-rate-api.sqlite3"
    monkeypatch.setattr(
        api.AppConfig,
        "from_env",
        classmethod(lambda cls: cls(database_url=f"sqlite:///{database_path}")),
    )
    monkeypatch.setattr(
        api,
        "providers_from_names",
        lambda provider_names: (RoutePriceProvider({("NKG", "TPE"): ("327.70", "USD")}),),
    )
    client = TestClient(app)

    response = client.post(
        "/api/trip-plan",
        json={
            "departure_date": "2026-07-01",
            "return_date": "2026-07-08",
            "include_shanghai_rail": False,
            "manual_exchange_rates": ["USD:CNY=7.20"],
        },
    )

    data = response.json()
    assert response.status_code == 200
    assert data["recommended_option"]["flight_amount"] == "2359.44"
    assert data["recommended_option"]["flight_currency"] == "CNY"
    assert data["recommended_option"]["total_amount"] == "2359.44"
    assert data["recommended_option"]["price_status"] == "priced"


def test_api_trip_plan_accepts_connection_city_fields(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "trip-plan-connection-api.sqlite3"
    monkeypatch.setattr(
        api.AppConfig,
        "from_env",
        classmethod(lambda cls: cls(database_url=f"sqlite:///{database_path}")),
    )
    client = TestClient(app)

    response = client.post(
        "/api/trip-plan",
        json={
            "origin_city": "Hangzhou",
            "destination_city": "Taipei",
            "departure_date": "2026-07-01",
            "return_date": "2026-07-08",
            "include_shanghai_rail": False,
            "rail_connection_city": "Shanghai",
            "airport_stopover_city": "Hong Kong",
            "flight_filter": "direct",
            "provider_names": ["skyscanner"],
        },
    )

    data = response.json()
    assert response.status_code == 200
    assert {option["option_id"] for option in data["options"]} == {
        "hangzhou-flight",
        "shanghai-rail-flight",
        "hongkong-airport-stopover",
    }
    assert data["request"]["flight_filter"] == "direct"


def test_api_search_aggregates_route_snapshots_from_other_sources(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "aggregate-api.sqlite3"
    monkeypatch.setattr(
        api.AppConfig,
        "from_env",
        classmethod(
            lambda cls: cls(
                database_url=f"sqlite:///{database_path}",
                exchange_rates={("CNY", "USD"): Decimal("0.14")},
            )
        ),
    )
    client = TestClient(app)

    import_response = client.post(
        "/api/import-browser",
        json={
            "filename": "fliggy.json",
            "save_snapshot": True,
            "content": """
            {
              "schema_version": "rft-browser-offers/v1",
              "source": "fliggy",
              "request": {
                "origin": "SHA",
                "destination": "TPE",
                "departure_date": "2026-06-02",
                "return_date": "2026-06-12",
                "allowed_markets": ["CN"],
                "allowed_currencies": ["CNY"]
              },
              "offers": [
                {
                  "provider": "fliggy",
                  "amount": "2225",
                  "currency": "CNY",
                  "flight_numbers": ["9C8951"],
                  "departure_time": "08:15",
                  "arrival_time": "10:15",
                  "link": "https://example.test/fliggy"
                }
              ]
            }
            """,
        },
    )
    assert import_response.status_code == 200

    search_response = client.post(
        "/api/search",
        json={
            "origin": "SHA",
            "destination": "TPE",
            "departure_date": "2026-06-02",
            "return_date": "2026-06-12",
            "provider_names": ["skyscanner"],
            "allowed_markets": ["US"],
            "allowed_currencies": ["USD"],
        },
    )

    data = search_response.json()
    assert search_response.status_code == 200
    providers = {offer["provider"] for offer in data["aggregate_offers"]}
    assert "fliggy-browser" in providers
    assert "skyscanner" in providers
    assert data["aggregate"]["provider_count"] >= 2
    assert data["aggregate_recommendations"]["lowest_price"]["provider"] == "fliggy-browser"
    assert data["aggregate_recommendations"]["lowest_price"]["currency"] == "USD"


def test_api_import_browser_export_rejects_invalid_content() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/import-browser",
        json={"filename": "bad.json", "content": "{}"},
    )

    assert response.status_code == 400


def test_api_import_browser_export_rejects_extra_fields() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/import-browser",
        json={
            "filename": "bad.json",
            "content": "{}",
            "db_url": "sqlite:///unexpected.sqlite3",
        },
    )

    assert response.status_code == 422
