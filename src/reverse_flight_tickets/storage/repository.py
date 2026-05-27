"""Repository interfaces for future SQLite/PostgreSQL storage."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from sqlalchemy import DateTime, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.monitoring.watchlist import WatchlistItem
from reverse_flight_tickets.storage.models import SearchSnapshot


class SearchRepository(Protocol):
    def save_search_snapshot(self, snapshot: SearchSnapshot) -> str:
        """Persist a search snapshot and return its id."""

    def get_search_snapshot(self, snapshot_id: str) -> SearchSnapshot | None:
        """Load a search snapshot by id."""

    def list_search_snapshots(self, request: SearchRequest | None = None) -> tuple[SearchSnapshot, ...]:
        """Load search snapshots, optionally filtered by canonical request."""


class InMemoryRepository:
    """Development repository used until durable storage is implemented."""

    def __init__(self) -> None:
        self._snapshots: dict[str, SearchSnapshot] = {}

    def save_search_snapshot(self, snapshot: SearchSnapshot) -> str:
        self._snapshots[snapshot.snapshot_id] = snapshot
        return snapshot.snapshot_id

    def get_search_snapshot(self, snapshot_id: str) -> SearchSnapshot | None:
        return self._snapshots.get(snapshot_id)

    def list_search_snapshots(self, request: SearchRequest | None = None) -> tuple[SearchSnapshot, ...]:
        snapshots = tuple(self._snapshots.values())
        if request is None:
            return snapshots
        return tuple(snapshot for snapshot in snapshots if snapshot.request.to_dict() == request.to_dict())


class Base(DeclarativeBase):
    pass


class SearchSnapshotRecord(Base):
    __tablename__ = "search_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    offers_json: Mapped[str] = mapped_column(Text, nullable=False)
    provider_runs_json: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WatchlistItemRecord(Base):
    __tablename__ = "watchlist_items"

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    target_amount: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provider_names_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
            request_json=_request_json(snapshot.request),
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
            return _snapshot_from_record(record)

    def list_search_snapshots(self, request: SearchRequest | None = None) -> tuple[SearchSnapshot, ...]:
        statement = select(SearchSnapshotRecord).order_by(SearchSnapshotRecord.captured_at)
        if request is not None:
            statement = statement.where(SearchSnapshotRecord.request_json == _request_json(request))
        with Session(self.engine) as session:
            return tuple(_snapshot_from_record(record) for record in session.scalars(statement))


class SqliteWatchlistRepository:
    """SQLite-backed watchlist repository for local scheduled runs."""

    def __init__(self, database_url: str) -> None:
        if database_url.startswith("sqlite:///"):
            db_path = Path(database_url.removeprefix("sqlite:///"))
            if db_path.parent != Path("."):
                db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(database_url, future=True)
        Base.metadata.create_all(self.engine)

    def add(self, item: WatchlistItem) -> str:
        record = WatchlistItemRecord(
            item_id=item.item_id,
            request_json=_request_json(item.request),
            target_amount=str(item.target_amount) if item.target_amount is not None else None,
            target_currency=item.target_currency,
            provider_names_json=json.dumps(list(item.provider_names), ensure_ascii=False),
            created_at=datetime.now(timezone.utc),
        )
        with Session(self.engine) as session:
            session.merge(record)
            session.commit()
        return item.item_id

    def list(self) -> tuple[WatchlistItem, ...]:
        with Session(self.engine) as session:
            return tuple(
                _watchlist_item_from_record(record)
                for record in session.scalars(select(WatchlistItemRecord).order_by(WatchlistItemRecord.created_at))
            )

    def get(self, item_id: str) -> WatchlistItem | None:
        with Session(self.engine) as session:
            record = session.scalar(
                select(WatchlistItemRecord).where(WatchlistItemRecord.item_id == item_id)
            )
            return _watchlist_item_from_record(record) if record else None


def _request_json(request: SearchRequest) -> str:
    return json.dumps(request.to_dict(), ensure_ascii=False, sort_keys=True)


def _snapshot_from_record(record: SearchSnapshotRecord) -> SearchSnapshot:
    return SearchSnapshot.from_serialized(
        snapshot_id=record.snapshot_id,
        request=json.loads(record.request_json),
        offers=json.loads(record.offers_json),
        provider_runs=json.loads(record.provider_runs_json),
        captured_at=record.captured_at,
    )


def _watchlist_item_from_record(record: WatchlistItemRecord) -> WatchlistItem:
    return WatchlistItem(
        item_id=record.item_id,
        request=SearchRequest.model_validate(json.loads(record.request_json)),
        target_amount=Decimal(record.target_amount) if record.target_amount else None,
        target_currency=record.target_currency,
        provider_names=tuple(json.loads(record.provider_names_json)),
    )
