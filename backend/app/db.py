import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, Integer, String, create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings

log = logging.getLogger(__name__)

if settings.database_url.startswith("sqlite:///"):
    Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,          # survive managed-database failovers and idle disconnects
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=1800,
    )

SessionLocal = sessionmaker(engine, expire_on_commit=False)


def utcnow() -> datetime:
    """Naive UTC, so SQLite and Postgres behave the same."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Device(Base):
    """One sharing home. Only the latest reading is kept; there is no history."""

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(32))
    cell_i: Mapped[int] = mapped_column(Integer)
    cell_j: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    heating_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    target_temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    indoor_temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    outdoor_temp: Mapped[float | None] = mapped_column(Float, nullable=True)


def init_db(attempts: int = 10) -> None:
    """Create tables, waiting for the database if it isn't reachable yet."""
    for attempt in range(1, attempts + 1):
        try:
            Base.metadata.create_all(engine)
            return
        except OperationalError as err:
            if attempt == attempts:
                raise
            log.warning("Database not ready (attempt %d/%d): %s", attempt, attempts, err.__class__.__name__)
            time.sleep(min(2 * attempt, 10))
