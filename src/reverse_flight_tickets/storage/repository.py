"""Repository interfaces for future SQLite/PostgreSQL storage."""

from __future__ import annotations

from typing import Protocol

from reverse_flight_tickets.storage.models import SearchSnapshot


class SearchRepository(Protocol):
    def save_search_snapshot(self, snapshot: SearchSnapshot) -> str:
        """Persist a search snapshot and return its id."""

    def get_search_snapshot(self, snapshot_id: str) -> SearchSnapshot | None:
        """Load a search snapshot by id."""


class InMemoryRepository:
    """Development repository used until durable storage is implemented."""

    def __init__(self) -> None:
        self._snapshots: dict[str, SearchSnapshot] = {}

    def save_search_snapshot(self, snapshot: SearchSnapshot) -> str:
        self._snapshots[snapshot.snapshot_id] = snapshot
        return snapshot.snapshot_id

    def get_search_snapshot(self, snapshot_id: str) -> SearchSnapshot | None:
        return self._snapshots.get(snapshot_id)
