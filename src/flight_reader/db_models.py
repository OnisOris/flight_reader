from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Interval,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flight_reader.db import Base


class TimestampMixin:
    """Mixin с единообразными полями аудита."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Operator(TimestampMixin, Base):
    """Оператор БАС."""

    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    extra: Mapped[Dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    flights: Mapped[List["Flight"]] = relationship(back_populates="operator")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "extra": self.extra or {},
        }


class UavType(TimestampMixin, Base):
    """Тип/модель беспилотного аппарата."""

    __tablename__ = "uav_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)

    flights: Mapped[List["Flight"]] = relationship(back_populates="uav_type")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "description": self.description,
        }


class Region(TimestampMixin, Base):
    """Регион РФ с геометрией границ."""

    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    geom: Mapped[Any] = mapped_column(Geometry(geometry_type="MULTIPOLYGON", srid=4326))

    flights_from: Mapped[List["Flight"]] = relationship(
        back_populates="region_from", foreign_keys="Flight.region_from_id"
    )
    flights_to: Mapped[List["Flight"]] = relationship(
        back_populates="region_to", foreign_keys="Flight.region_to_id"
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
        }


class RawMessage(TimestampMixin, Base):
    """Сырые сообщения, полученные от внешних систем."""

    __tablename__ = "raw_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sender: Mapped[Optional[str]] = mapped_column(String(128))

    flights: Mapped[List["Flight"]] = relationship(back_populates="raw_message")


class Flight(TimestampMixin, Base):
    """Фактический полет БАС."""

    __tablename__ = "flights"
    __table_args__ = (
        UniqueConstraint(
            "flight_id",
            "takeoff_time",
            "landing_time",
            name="uq_flights_flight_time",
        ),
        Index("ix_flights_takeoff", "takeoff_time"),
        Index("ix_flights_landing", "landing_time"),
        Index("ix_flights_operator", "operator_id"),
        Index("ix_flights_uav_type", "uav_type_id"),
        Index("ix_flights_region_from", "region_from_id"),
        Index("ix_flights_region_to", "region_to_id"),
        Index("ix_flights_geom_takeoff", "geom_takeoff", postgresql_using="gist"),
        Index("ix_flights_geom_landing", "geom_landing", postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    flight_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"), nullable=False)
    uav_type_id: Mapped[int] = mapped_column(ForeignKey("uav_types.id"), nullable=False)
    takeoff_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    landing_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration: Mapped[Optional[timedelta]] = mapped_column(Interval())
    geom_takeoff: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326), nullable=True
    )
    geom_landing: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326), nullable=True
    )
    region_from_id: Mapped[Optional[int]] = mapped_column(ForeignKey("regions.id"))
    region_to_id: Mapped[Optional[int]] = mapped_column(ForeignKey("regions.id"))
    raw_msg_id: Mapped[Optional[int]] = mapped_column(ForeignKey("raw_messages.id"))

    operator: Mapped[Operator] = relationship(back_populates="flights")
    uav_type: Mapped[UavType] = relationship(back_populates="flights")
    raw_message: Mapped[Optional[RawMessage]] = relationship(back_populates="flights")
    region_from: Mapped[Optional[Region]] = relationship(
        back_populates="flights_from", foreign_keys=[region_from_id]
    )
    region_to: Mapped[Optional[Region]] = relationship(
        back_populates="flights_to", foreign_keys=[region_to_id]
    )


class FlightHistory(Base):
    """Исторические записи по полетам (заполняется триггерами)."""

    __tablename__ = "flights_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    flight_id: Mapped[int] = mapped_column(ForeignKey("flights.id"), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)


class User(TimestampMixin, Base):
    """Пользователь системы (OAuth через Keycloak)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    auth_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(255))

    upload_logs: Mapped[List["UploadLog"]] = relationship(back_populates="user")
    calculations: Mapped[List["Calculation"]] = relationship(back_populates="user")
    reports: Mapped[List["Report"]] = relationship(back_populates="user")


class UploadLog(TimestampMixin, Base):
    """История загрузок файлов операторов."""

    __tablename__ = "upload_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source_file: Mapped[Optional[str]] = mapped_column(String(255))
    flight_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="upload_logs")


class Calculation(TimestampMixin, Base):
    """Журнал агрегирующих расчетов."""

    __tablename__ = "calculations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    parameters: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result_summary: Mapped[Dict[str, Any] | None] = mapped_column(JSONB)

    user: Mapped[User] = relationship(back_populates="calculations")


class Report(TimestampMixin, Base):
    """Сохраненные JSON-отчеты."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    report_type: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    parameters: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)

    user: Mapped[User] = relationship(back_populates="reports")
