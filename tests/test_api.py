from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from reverse_flight_tickets import api
from reverse_flight_tickets.api import app


def test_api_health() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


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
