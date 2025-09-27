from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from flight_reader.api.schemas import (
    FlightSchema,
    OperatorSchema,
    PointSchema,
    RegionSchema,
    UavTypeSchema,
)
from flight_reader.db import get_session
from flight_reader.db_models import Flight

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
