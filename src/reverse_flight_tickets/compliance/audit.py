"""Audit log primitives for provider calls and booking handoff events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: str
    provider: str | None = None
    status: str = "recorded"
    metadata: Mapping[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, object]:
        return {
            "event_type": self.event_type,
            "provider": self.provider,
            "status": self.status,
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
        }


class InMemoryAuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self._events.append(event)

    def list(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)
