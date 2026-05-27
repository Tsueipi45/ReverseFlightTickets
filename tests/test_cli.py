from pathlib import Path

from reverse_flight_tickets.cli import _excluded_carriers, _format_table, _request_from_values
from reverse_flight_tickets.config import AppConfig
from reverse_flight_tickets.domain import Layover, Offer, SearchRequest, Segment, TicketingType
from reverse_flight_tickets.search import SearchRunResult


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


def test_table_output_includes_airline_and_flight_columns() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "LHR",
            "destination": "JFK",
            "departure_date": "2026-10-01",
        }
    )
    offer = Offer(
        provider="duffel",
        source_market="US",
        currency="USD",
        total_amount="218.54",
        comparable_amount="218.54",
        segments=(
            Segment(
                origin="LHR",
                destination="JFK",
                departure_date=request.departure_date,
                departure_time="2026-10-01T12:30:00",
                arrival_time="2026-10-01T20:28:00",
                marketing_carrier="BA",
                flight_number="1516",
            ),
        ),
        travel_duration_minutes=478,
        layovers=(Layover(airport="KEF", duration_minutes=255),),
        ticketing_type=TicketingType.SINGLE_TICKET,
    )

    table = _format_table(SearchRunResult(request=request, offers=(offer,), provider_runs=()))

    assert "airlines" in table
    assert "flights" in table
    assert "depart" in table
    assert "arrive" in table
    assert "travel_time" in table
    assert "transfers" in table
    assert "layover_time" in table
    assert "BA" in table
    assert "BA1516" in table
    assert "2026-10-01T12:30:00" in table
    assert "2026-10-01T20:28:00" in table
    assert "7h58m" in table
    assert "KEF" in table
    assert "KEF 4h15m" in table


def test_cli_excludes_duffel_test_carrier_by_default() -> None:
    assert _excluded_carriers(exclude_carrier=(), include_test_carriers=False) == ("ZZ",)


def test_cli_can_include_test_carriers() -> None:
    assert _excluded_carriers(exclude_carrier=(), include_test_carriers=True) == ()


def test_cli_adds_custom_excluded_carriers() -> None:
    assert _excluded_carriers(exclude_carrier=("ba", "ZZ"), include_test_carriers=False) == (
        "ZZ",
        "BA",
    )
