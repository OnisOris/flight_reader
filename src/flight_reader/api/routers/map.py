"""API-эндпоинты карты, работающие через PostgreSQL/PostGIS."""

from __future__ import annotations

import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, union
from sqlalchemy.orm import Session

from flight_reader.db import get_session
from flight_reader.db_models import Flight, Region

router = APIRouter()


@router.get("/map/regions")
def list_regions(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    stat_type: Literal["flights", "delays", "cargo", "all"] | None = Query(
        default=None
    ),
    direction: Literal["domestic", "international", "all"] | None = Query(default=None),
    session: Session = Depends(get_session),
):
    """Возвращает агрегированную статистику по регионам без геометрии.

    :param date_from: Нижняя граница интервала дат вылетов (включительно).
    :type date_from: datetime.date | None
    :param date_to: Верхняя граница интервала дат вылетов (включительно).
    :type date_to: datetime.date | None
    :param stat_type: Вид статистики; поддерживаются ``None``, ``"flights"`` и ``"all"``.
    :type stat_type: Literal["flights", "delays", "cargo", "all"] | None
    :param direction: Фильтр направления: ``"domestic"`` — оба региона заданы, ``"international"`` — хотя бы один отсутствует, ``"all"`` — без фильтра.
    :type direction: Literal["domestic", "international", "all"] | None
    :param session: Сессия SQLAlchemy, внедряемая через зависимость FastAPI.
    :type session: sqlalchemy.orm.Session
    :return: Список словарей с кодом, названием региона и подсчитанным числом полетов.
    :rtype: list[dict[str, str | int]]
    """
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be before date_to")

    flights_stmt = select(
        Flight.id.label("flight_id"),
        Flight.region_from_id,
        Flight.region_to_id,
    )

    if date_from is not None:
        flights_stmt = flights_stmt.where(func.date(Flight.takeoff_time) >= date_from)
    if date_to is not None:
        flights_stmt = flights_stmt.where(func.date(Flight.takeoff_time) <= date_to)

    if direction in {"domestic", "international"}:
        if direction == "domestic":
            flights_stmt = flights_stmt.where(
                Flight.region_from_id.isnot(None),
                Flight.region_to_id.isnot(None),
            )
        else:  # international
            flights_stmt = flights_stmt.where(
                or_(Flight.region_from_id.is_(None), Flight.region_to_id.is_(None))
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

    stmt = (
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

    rows = session.execute(stmt).all()
    return [
        {"code": code, "name": name, "flight_count": flight_count}
        for code, name, flight_count in rows
    ]


@router.get("/map/regions/{code}")
def get_region(code: str, session: Session = Depends(get_session)):
    """Детали по определенному региону."""
    stmt = select(Region).where(func.lower(Region.code) == code.lower())
    region = session.execute(stmt).scalar_one_or_none()
    if region is None:
        raise HTTPException(status_code=404, detail="Region not found")
    geom_geojson = session.execute(
        select(func.ST_AsGeoJSON(Region.geom)).where(Region.id == region.id)
    ).scalar_one()
    data = region.to_dict()
    data["geometry"] = json.loads(geom_geojson) if geom_geojson else None
    return data
