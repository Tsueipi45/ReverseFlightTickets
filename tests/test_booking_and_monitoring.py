from decimal import Decimal

from reverse_flight_tickets.booking import BookingHandoff, OrderRecord, OrderStatus
from reverse_flight_tickets.domain import Offer, RiskFlag, SearchRequest
from reverse_flight_tickets.monitoring import (
    InMemoryWatchlistRepository,
    WatchlistItem,
    evaluate_price_drop,
)


def _offer() -> Offer:
    return Offer(
        provider="manual",
        source_market="US",
        currency="USD",
        total_amount="500.00",
        booking_link="https://example.com",
        risk_flags=(RiskFlag.MANUAL_CHECK_REQUIRED,),
    )


def test_booking_handoff_and_order_record_flow() -> None:
    offer = _offer()
    handoff = BookingHandoff.from_offer(offer)
    order = OrderRecord.from_offer(offer, notes="verified manually")
    confirmed = order.mark_confirmed(provider_order_id="abc123")
    ticketed = confirmed.mark_ticketed(("0012345678901",))

    assert handoff.manual_check_required is True
    assert handoff.booking_link == "https://example.com"
    assert order.status == OrderStatus.PENDING_MANUAL_CONFIRMATION
    assert confirmed.status == OrderStatus.CONFIRMED
    assert confirmed.provider_order_id == "abc123"
    assert ticketed.status == OrderStatus.TICKETED
    assert ticketed.ticket_numbers == ("0012345678901",)


def test_watchlist_repository_and_price_drop_alert() -> None:
    request = SearchRequest.from_mapping(
        {
            "origin": "PVG",
            "destination": "LAX",
            "departure_date": "2026-10-01",
        }
    )
    item = WatchlistItem(
        request=request,
        target_amount=Decimal("550.00"),
        target_currency="USD",
        provider_names=("manual",),
    )
    repository = InMemoryWatchlistRepository()

    item_id = repository.add(item)
    alert = evaluate_price_drop(_offer(), Decimal("550.00"))

    assert repository.get(item_id) == item
    assert repository.list() == (item,)
    assert alert is not None
    assert alert.provider == "manual"
    assert item.to_dict()["provider_names"] == ["manual"]
