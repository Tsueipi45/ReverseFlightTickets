"""Local order records created after manual confirmation."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from reverse_flight_tickets.domain import Offer


class OrderStatus(StrEnum):
    PENDING_MANUAL_CONFIRMATION = "pending_manual_confirmation"
    CONFIRMED = "confirmed"
    TICKETED = "ticketed"
    CANCELLED = "cancelled"


class OrderRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    offer: Offer
    status: OrderStatus = OrderStatus.PENDING_MANUAL_CONFIRMATION
    order_id: str = Field(default_factory=lambda: str(uuid4()))
    provider_order_id: str | None = None
    ticket_numbers: tuple[str, ...] = ()
    notes: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_offer(cls, offer: Offer, *, notes: str | None = None) -> "OrderRecord":
        return cls(offer=offer, notes=notes)

    def mark_confirmed(
        self,
        *,
        provider_order_id: str | None = None,
        notes: str | None = None,
    ) -> "OrderRecord":
        return self.model_copy(
            update={
                "status": OrderStatus.CONFIRMED,
                "provider_order_id": provider_order_id or self.provider_order_id,
                "notes": notes or self.notes,
                "updated_at": datetime.now(timezone.utc),
            }
        )

    def mark_ticketed(self, ticket_numbers: tuple[str, ...]) -> "OrderRecord":
        return self.model_copy(
            update={
                "status": OrderStatus.TICKETED,
                "ticket_numbers": ticket_numbers,
                "updated_at": datetime.now(timezone.utc),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "order_id": self.order_id,
            "provider": self.offer.provider,
            "status": self.status.value,
            "provider_order_id": self.provider_order_id,
            "ticket_numbers": list(self.ticket_numbers),
            "notes": self.notes,
            "offer": self.offer.to_dict(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
