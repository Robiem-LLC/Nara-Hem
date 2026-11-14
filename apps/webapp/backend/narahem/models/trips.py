"""Trips indexed for history, and their start and end labels."""

from sqlalchemy import (
    BigInteger,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class IndexedTrip(Base):
    """Server index of a trip summary, readable by the original event's recipients. Coordinates
    and metrics are encrypted with the server's storage key.
    """

    __tablename__ = "indexed_trips"
    event_id: Mapped[str] = mapped_column(
        ForeignKey("encrypted_records.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[str] = mapped_column(String(32), index=True)
    device_id: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[int] = mapped_column(BigInteger)
    ended_at: Mapped[int] = mapped_column(BigInteger)
    trip_id: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    encrypted_trip: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[float] = mapped_column(Float, default=0)
    __table_args__ = (Index("ix_indexed_trips_member_date", "account_id", "ended_at", "event_id"),)


class TripLabel(Base):
    """The names for a trip's start and end, decided once by the server so every app shows the
    same text.
    """

    __tablename__ = "trip_labels"
    event_id: Mapped[str] = mapped_column(
        ForeignKey("indexed_trips.event_id", ondelete="CASCADE"), primary_key=True
    )
    labels: Mapped[str | None] = mapped_column(
        Text
    )  # encrypted {"start": {"place": id} | {"address": text}, "end": ...}
    attempts: Mapped[int] = mapped_column(Integer, default=0)
