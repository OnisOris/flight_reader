"""API-эндпоинты карты, работающие через PostgreSQL/PostGIS."""

from __future__ import annotations

import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from flight_reader.db import get_session
from flight_reader.db_models import Region

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
    """Возвращает только список регионов (code, name) без геометрии."""
    _ = (date_from, date_to, stat_type, direction)
    stmt = select(Region.code, Region.name).order_by(Region.code)
    rows = session.execute(stmt).all()
    return [{"code": code, "name": name} for code, name in rows]


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
