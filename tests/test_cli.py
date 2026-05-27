from pathlib import Path

from reverse_flight_tickets.cli import _request_from_values
from reverse_flight_tickets.config import AppConfig


def test_cli_request_merges_json_and_overrides(tmp_path: Path) -> None:
    json_path = tmp_path / "request.json"
    json_path.write_text(
        """
        {
          "origin": "PVG",
          "destination": "LAX",
          "departure_date": "2026-10-01",
          "allowed_markets": "US",
          "allowed_currencies": "USD"
        }
        """,
        encoding="utf-8",
    )

    request = _request_from_values(
        config=AppConfig(),
        json_input=json_path,
        origin=None,
        destination="SFO",
        departure_date=None,
        return_date=None,
        passenger_count=2,
        cabin="business",
        markets=None,
        currencies=None,
        max_layover_hours=None,
        include_split_ticket=False,
        include_self_transfer=False,
        include_hidden_city=False,
    )

    assert request.destination == "SFO"
    assert request.passengers.adults == 2
    assert request.cabin == "business"
