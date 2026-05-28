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
