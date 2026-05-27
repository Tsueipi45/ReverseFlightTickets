from reverse_flight_tickets.compliance import InMemoryAuditLog, default_terms_registry
from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.providers import SkyscannerProvider
from reverse_flight_tickets.search import SearchOrchestrator


def test_default_terms_registry_marks_deeplink_sources() -> None:
    registry = default_terms_registry()
    terms = registry.get("skyscanner")

    assert terms is not None
    assert terms.access_mode == "manual_deep_link"
    assert terms.production_verified is False


def test_orchestrator_records_provider_audit_events() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
        }
    )
    audit_log = InMemoryAuditLog()

    __import__("asyncio").run(
        SearchOrchestrator([SkyscannerProvider()], audit_log=audit_log).search(request)
    )

    events = audit_log.list()
    assert [event.status for event in events] == ["started", "ok"]
    assert events[0].metadata["access_mode"] == "manual_deep_link"
