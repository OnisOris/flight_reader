from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import to_shape
from sqlalchemy import func, or_, select, union
from sqlalchemy.orm import Session, selectinload

from flight_reader.api.schemas import (
    FlightSchema,
    FlightStatsRegionSchema,
    FlightStatsSchema,
    OperatorSchema,
    PointSchema,
    RegionSchema,
    UavTypeSchema,
)
from flight_reader.db import get_session
from flight_reader.db_models import Flight, Region

router = APIRouter()


def _point_from_geometry(geom) -> Optional[PointSchema]:
    if geom is None:
        return None
    shape = to_shape(geom)
    return PointSchema(lat=shape.y, lon=shape.x)


def _serialize_flight(flight: Flight) -> FlightSchema:
    return FlightSchema(
        id=flight.id,
        flight_id=flight.flight_id,
        takeoff_time=flight.takeoff_time,
        landing_time=flight.landing_time,
        duration_seconds=flight.duration.total_seconds() if flight.duration else None,
        operator=OperatorSchema.model_validate(flight.operator) if flight.operator else None,
        uav_type=UavTypeSchema.model_validate(flight.uav_type) if flight.uav_type else None,
        region_from=RegionSchema.model_validate(flight.region_from) if flight.region_from else None,
        region_to=RegionSchema.model_validate(flight.region_to) if flight.region_to else None,
        takeoff_point=_point_from_geometry(flight.geom_takeoff),
        landing_point=_point_from_geometry(flight.geom_landing),
        raw_message_id=flight.raw_msg_id,
    )


@router.get("/flights", response_model=List[FlightSchema])
def list_flights(
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    operator_id: Optional[int] = Query(default=None),
    uav_type_id: Optional[int] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> List[FlightSchema]:
    """Возвращает список полетов с возможностью фильтрации."""

    stmt = (
        select(Flight)
        .options(
            selectinload(Flight.operator),
            selectinload(Flight.uav_type),
            selectinload(Flight.region_from),
            selectinload(Flight.region_to),
        )
        .order_by(Flight.takeoff_time.desc().nullslast())
        .limit(limit)
        .offset(offset)
    )

    if date_from is not None:
        stmt = stmt.where(Flight.takeoff_time >= date_from)
    if date_to is not None:
        stmt = stmt.where(Flight.takeoff_time <= date_to)
    if operator_id is not None:
        stmt = stmt.where(Flight.operator_id == operator_id)
    if uav_type_id is not None:
        stmt = stmt.where(Flight.uav_type_id == uav_type_id)

    flights = session.execute(stmt).scalars().all()
    return [_serialize_flight(flight) for flight in flights]


@router.get("/flights/stats", response_model=FlightStatsSchema)
def get_flight_stats(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    direction: Literal["domestic", "international", "all"] | None = Query(default=None),
    region_codes: list[str] | None = Query(default=None),
    session: Session = Depends(get_session),
) -> FlightStatsSchema:
    """Агрегирует количество полетов за период.

    :param date_from: Нижняя граница интервала дат вылетов (включительно).
    :type date_from: datetime.date | None
    :param date_to: Верхняя граница интервала дат вылетов (включительно).
    :type date_to: datetime.date | None
    :param direction: Фильтр направления: ``"domestic"`` — оба региона заданы, ``"international"`` — есть хотя бы один пропуск, ``"all"``/``None`` — без фильтра.
    :type direction: Literal["domestic", "international", "all"] | None
    :param region_codes: Список кодов регионов (ISO 3166-2) для фильтрации статистики; если не задан, учитываются все регионы.
    :type region_codes: list[str] | None
    :param session: Сессия SQLAlchemy, внедряемая через зависимость FastAPI.
    :type session: sqlalchemy.orm.Session
    :return: Общее число полетов и список подсчетов по регионам.
    :rtype: FlightStatsSchema
    """

    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be before date_to")

    normalized_direction: Literal["domestic", "international", "all"] | None = direction
    if normalized_direction == "all":
        normalized_direction = None

    normalized_codes = [] if region_codes is None else [code.strip() for code in region_codes if code and code.strip()]
    lower_codes = [code.lower() for code in normalized_codes]

    region_ids: list[int] = []
    if lower_codes:
        region_rows = session.execute(
            select(Region.id, Region.code).where(func.lower(Region.code).in_(lower_codes))
        ).all()
        found_codes = {row.code.lower(): row.id for row in region_rows}
        missing = [code for code in normalized_codes if code.lower() not in found_codes]
        if missing:
            raise HTTPException(status_code=404, detail={"missing_region_codes": missing})
        region_ids = list(found_codes.values())

    flights_stmt = select(
        Flight.id.label("flight_id"),
        Flight.region_from_id,
        Flight.region_to_id,
    )

    if date_from is not None:
        flights_stmt = flights_stmt.where(func.date(Flight.takeoff_time) >= date_from)
    if date_to is not None:
        flights_stmt = flights_stmt.where(func.date(Flight.takeoff_time) <= date_to)

    if normalized_direction in {"domestic", "international"}:
        if normalized_direction == "domestic":
            flights_stmt = flights_stmt.where(
                Flight.region_from_id.isnot(None),
                Flight.region_to_id.isnot(None),
            )
        else:
            flights_stmt = flights_stmt.where(
                or_(Flight.region_from_id.is_(None), Flight.region_to_id.is_(None))
            )

    if region_ids:
        flights_stmt = flights_stmt.where(
            or_(
                Flight.region_from_id.in_(region_ids),
                Flight.region_to_id.in_(region_ids),
            )
        )

    flights_subq = flights_stmt.subquery()

    flight_regions_subq = (
        union(
            select(
                flights_subq.c.flight_id,
                flights_subq.c.region_from_id.label("region_id"),
            ).where(flights_subq.c.region_from_id.isnot(None)),
            select(
                flights_subq.c.flight_id,
                flights_subq.c.region_to_id.label("region_id"),
            ).where(flights_subq.c.region_to_id.isnot(None)),
        )
    ).subquery()

    total_stmt = select(func.count(func.distinct(flights_subq.c.flight_id)))
    total_flights = session.execute(total_stmt).scalar_one()

    regions_stmt = (
        select(
            Region.code,
            Region.name,
            func.coalesce(func.count(flight_regions_subq.c.flight_id), 0).label(
                "flight_count"
            ),
        )
        .select_from(Region)
        .outerjoin(flight_regions_subq, Region.id == flight_regions_subq.c.region_id)
        .group_by(Region.id)
        .order_by(Region.code)
    )

    if region_ids:
        regions_stmt = regions_stmt.where(Region.id.in_(region_ids))

    regions_rows = session.execute(regions_stmt).all()

    regions_payload = [
        FlightStatsRegionSchema(code=code, name=name, flight_count=flight_count)
        for code, name, flight_count in regions_rows
    ]

    return FlightStatsSchema(total_flights=total_flights, regions=regions_payload)


@router.get("/flights/{flight_pk}", response_model=FlightSchema)
def get_flight(flight_pk: int, session: Session = Depends(get_session)) -> FlightSchema:
    """Возвращает детальную информацию по одному полету."""

    stmt = (
        select(Flight)
        .where(Flight.id == flight_pk)
        .options(
            selectinload(Flight.operator),
            selectinload(Flight.uav_type),
            selectinload(Flight.region_from),
            selectinload(Flight.region_to),
        )
    )
    flight = session.execute(stmt).scalar_one_or_none()
    if flight is None:
        raise HTTPException(status_code=404, detail="Flight not found")
    return _serialize_flight(flight)
