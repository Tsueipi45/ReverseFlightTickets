import json
from pathlib import Path

from reverse_flight_tickets.importers import import_browser_export, import_browser_export_text
from reverse_flight_tickets.storage import SqliteSearchRepository


def test_import_browser_export_normalizes_and_ranks_json(tmp_path: Path) -> None:
    export_path = tmp_path / "ctrip.json"
    export_path.write_text(
        json.dumps(
            {
                "schema_version": "rft-browser-offers/v1",
                "source": "ctrip",
                "page_url": "https://flights.ctrip.com/online/list/round-sha-tpe",
                "captured_at": "2026-05-29T03:00:00Z",
                "request": {
                    "origin": "SHA",
                    "destination": "TPE",
                    "departure_date": "2026-05-30",
                    "return_date": "2026-06-02",
                    "allowed_markets": ["CN"],
                    "allowed_currencies": ["CNY"],
                },
                "offers": [
                    {
                        "provider": "ctrip",
                        "price": {"amount": "1800", "currency": "CNY"},
                        "airline": "东方航空",
                        "flight_numbers": ["MU5001"],
                        "departure_time": "08:00",
                        "arrival_time": "10:00",
                        "stops": "direct",
                        "link": "https://flights.ctrip.com/a",
                    },
                    {
                        "provider": "ctrip",
                        "price": {"amount": "1200", "currency": "CNY"},
                        "airline": "中华航空",
                        "flight_numbers": ["CI502"],
                        "departure_time": "12:00",
                        "arrival_time": "14:00",
                        "stops": "direct",
                        "link": "https://flights.ctrip.com/b",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result, snapshot_id = import_browser_export(export_path)

    assert snapshot_id is None
    assert result.request.origin == "SHA"
    assert result.request.destination == "TPE"
    assert result.request.return_date is not None
    assert [offer.total_amount for offer in result.offers] == [1200, 1800]
    assert result.offers[0].provider == "ctrip-browser"
    assert result.offers[0].manual_check_required is True
    assert result.offers[0].segments[0].marketing_carrier == "CI"
    assert result.offers[0].segments[0].flight_number == "502"
    assert "browser import uses only already-rendered visible cards" in result.warnings[0]


def test_import_browser_export_saves_snapshot(tmp_path: Path) -> None:
    export_path = tmp_path / "fliggy.json"
    export_path.write_text(
        json.dumps(
            {
                "schema_version": "rft-browser-offers/v1",
                "source": "fliggy",
                "page_url": "https://sijipiao.fliggy.com/ie/flight_search_result.htm",
                "request": {
                    "origin": "DLC",
                    "destination": "TPE",
                    "departure_date": "2026-05-29",
                    "allowed_markets": ["CN"],
                    "allowed_currencies": ["CNY"],
                },
                "offers": [
                    {
                        "provider": "fliggy",
                        "amount": "900",
                        "currency": "CNY",
                        "airline": "中国国航",
                        "flight_numbers": ["CA1234"],
                        "departure_time": "09:30",
                        "arrival_time": "15:20",
                        "stops": "中转 PEK",
                        "link": "https://example.test/book",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    db_url = f"sqlite:///{tmp_path / 'snapshots.sqlite3'}"

    result, snapshot_id = import_browser_export(
        export_path,
        save_snapshot=True,
        db_url=db_url,
    )

    assert snapshot_id
    loaded = SqliteSearchRepository(db_url).get_search_snapshot(snapshot_id or "")
    assert loaded is not None
    assert loaded.request == result.request
    assert loaded.offers[0].offer.provider == "fliggy-browser"
    assert loaded.offers[0].offer.layovers[0].airport == "PEK"


def test_import_browser_export_reads_csv(tmp_path: Path) -> None:
    export_path = tmp_path / "browser.csv"
    export_path.write_text(
        "\ufeffschema_version,source,provider,page_url,origin,destination,departure_date,currency,amount,airline,flight_numbers,departure_time,arrival_time,stops,link,raw_text\n"
        "rft-browser-offers/v1,ctrip,ctrip,https://example.test,SHA,TPE,2026-05-30,CNY,888,东方航空,MU5001,08:00,10:00,direct,https://example.test/a,text\n",
        encoding="utf-8",
    )

    result, _snapshot_id = import_browser_export(export_path)

    assert len(result.offers) == 1
    assert result.request.origin == "SHA"
    assert result.offers[0].total_amount == 888
    assert result.offers[0].segments[0].flight_number == "5001"


def test_import_browser_export_falls_back_to_fliggy_search_journey_url() -> None:
    page_url = (
        "https://sijipiao.fliggy.com/ie/flight_search_result.htm?"
        "searchJourney=%5B%7B%22depCityCode%22%3A%22SHA%22%2C%22arrCityCode%22%3A%22TPE%22%2C"
        "%22depDate%22%3A%222026-06-02%22%7D%2C%7B%22depCityCode%22%3A%22TPE%22%2C"
        "%22arrCityCode%22%3A%22SHA%22%2C%22depDate%22%3A%222026-06-12%22%7D%5D"
        "&childPassengerNum=0&infantPassengerNum=0&tripType=1"
    )
    content = json.dumps(
        {
            "schema_version": "rft-browser-offers/v1",
            "source": "fliggy",
            "page_url": page_url,
            "request": {
                "allowed_markets": ["CN"],
                "allowed_currencies": ["CNY"],
                "passenger_count": 1,
                "cabin": "economy",
                "passengers": {"adults": 1, "children": 0, "infants": 0},
            },
            "offers": [
                {
                    "provider": "fliggy",
                    "amount": "2225",
                    "currency": "CNY",
                    "airline": "春秋航空",
                    "flight_numbers": ["9C8951", "T210"],
                    "departure_time": "08:15",
                    "arrival_time": "10:15",
                    "link": page_url,
                }
            ],
        },
        ensure_ascii=False,
    )

    result, _snapshot_id = import_browser_export_text(content, filename="fliggy.json")

    assert result.request.origin == "SHA"
    assert result.request.destination == "TPE"
    assert result.request.departure_date.isoformat() == "2026-06-02"
    assert result.request.return_date is not None
    assert result.request.return_date.isoformat() == "2026-06-12"
    assert result.offers[0].segments[0].origin == "SHA"
    assert result.offers[0].segments[0].destination == "TPE"
