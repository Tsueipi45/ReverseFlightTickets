"""Repository interfaces for future SQLite/PostgreSQL storage."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy import DateTime, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

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


class Base(DeclarativeBase):
    pass


class SearchSnapshotRecord(Base):
    __tablename__ = "search_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    offers_json: Mapped[str] = mapped_column(Text, nullable=False)
    provider_runs_json: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SqliteSearchRepository:
    """SQLite-backed snapshot repository for local MVP persistence."""

    def __init__(self, database_url: str) -> None:
        if database_url.startswith("sqlite:///"):
            db_path = Path(database_url.removeprefix("sqlite:///"))
            if db_path.parent != Path("."):
                db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(database_url, future=True)
        Base.metadata.create_all(self.engine)

    def save_search_snapshot(self, snapshot: SearchSnapshot) -> str:
        record = SearchSnapshotRecord(
            snapshot_id=snapshot.snapshot_id,
            request_json=json.dumps(snapshot.request.to_dict(), ensure_ascii=False),
            offers_json=json.dumps(
                [offer.to_dict() for offer in snapshot.offers],
                ensure_ascii=False,
            ),
            provider_runs_json=json.dumps(
                [run.model_dump(mode="json") for run in snapshot.provider_runs],
                ensure_ascii=False,
            ),
            captured_at=snapshot.captured_at,
        )
        with Session(self.engine) as session:
            session.merge(record)
            session.commit()
        return snapshot.snapshot_id

    def get_search_snapshot(self, snapshot_id: str) -> SearchSnapshot | None:
        with Session(self.engine) as session:
            record = session.scalar(
                select(SearchSnapshotRecord).where(SearchSnapshotRecord.snapshot_id == snapshot_id)
            )
            if record is None:
                return None
            return SearchSnapshot.from_serialized(
                snapshot_id=record.snapshot_id,
                request=json.loads(record.request_json),
                offers=json.loads(record.offers_json),
                provider_runs=json.loads(record.provider_runs_json),
                captured_at=record.captured_at,
            )
