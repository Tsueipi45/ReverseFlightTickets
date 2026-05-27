"""Booking handoff models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from reverse_flight_tickets.booking.checklist import build_pre_purchase_checklist
from reverse_flight_tickets.domain import Offer


class BookingHandoff(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    booking_link: str | None
    manual_check_required: bool
    checklist: tuple[str, ...]

    @classmethod
    def from_offer(cls, offer: Offer) -> "BookingHandoff":
        return cls(
            provider=offer.provider,
            booking_link=offer.booking_link,
            manual_check_required=offer.manual_check_required,
            checklist=build_pre_purchase_checklist(offer),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "booking_link": self.booking_link,
            "manual_check_required": self.manual_check_required,
            "checklist": list(self.checklist),
        }
