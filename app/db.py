import os, uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, String, DateTime, Integer, Numeric, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, ExcludeConstraint

load_dotenv(os.getenv("FLEET_ENV", "/etc/fleet.env"))
# Общий ключ LLM для демо-сервисов (доступ по ACL); если файла нет или он недоступен — работает OpenRouter
try:
    load_dotenv(os.getenv("AI_ENV", "/etc/demo-ai/deepseek.env"))
except OSError:
    pass
ROOT = Path(__file__).resolve().parent.parent
FILES = Path(os.getenv("FILE_ROOT", "/var/lib/fleet/files"))
URL = os.getenv("PUBLIC_URL", "https://fleet.shvarev-demo.ru")


def now():
    return datetime.now(timezone.utc)


def uid():
    return uuid.uuid4().hex


# A request never waits for a row lock forever, and a forgotten open transaction does not hold locks for long.
engine = create_engine(
    os.environ["DATABASE_URL"], pool_size=4, max_overflow=2, pool_pre_ping=True,
    connect_args={"options": "-c lock_timeout=15000 -c idle_in_transaction_session_timeout=300000"},
)
Session = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Space(Base):
    __tablename__ = "spaces"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(24), default="owner")
    touched: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)


class Item(Base):
    __tablename__ = "items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    space: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    code: Mapped[str] = mapped_column(String(80))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("space", "kind", "code"), Index("items_space_kind", "space", "kind"))


class AccessToken(Base):
    __tablename__ = "access_tokens"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    space: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    space: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    vehicle: Mapped[str] = mapped_column(String(32))
    contract: Mapped[str] = mapped_column(String(32))
    period: Mapped[object] = mapped_column(TSTZRANGE)
    state: Mapped[str] = mapped_column(String(20), default="hold")
    expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        ExcludeConstraint(
            ("space", "="),
            ("vehicle", "="),
            ("period", "&&"),
            where="state IN ('hold','confirmed','active')",
            using="gist",
            name="no_double_booking",
        ),
    )


class Entry(Base):
    __tablename__ = "entries"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    space: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    vehicle: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    contract: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    amount: Mapped[object] = mapped_column(Numeric(14, 2))
    date: Mapped[str] = mapped_column(String(10), index=True)
    key: Mapped[str] = mapped_column(String(150))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (UniqueConstraint("space", "key"),)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    space: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    target: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(250))
    role: Mapped[str] = mapped_column(String(24))
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)


class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    space: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(150))
    result: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("space", "key"),)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    space: Mapped[str | None] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    due: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    lease: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)


class Usage(Base):
    __tablename__ = "usage"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    space: Mapped[str | None] = mapped_column(
        ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model: Mapped[str] = mapped_column(String(100))
    cost: Mapped[object] = mapped_column(Numeric(10, 6))
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    ms: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class System(Base):
    __tablename__ = "system"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)


@contextmanager
def db():
    s = Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
