"""API-эндпоинты карты, работающие через PostgreSQL."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from flight_reader.db import get_session
from flight_reader.db_models import MapRegion

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
    """Возвращает список регионов с path и code региона."""
    _ = (date_from, date_to, stat_type, direction)
    regions = session.execute(select(MapRegion).order_by(MapRegion.code)).scalars().all()
    return [region.to_dict() for region in regions]


@router.get("/map/regions/{code}")
def get_region(code: str, session: Session = Depends(get_session)):
    """Детали по определенному региону."""
    region = session.execute(
        select(MapRegion).where(func.lower(MapRegion.code) == code.lower())
    ).scalar_one_or_none()
    if region is None:
        raise HTTPException(status_code=404, detail="Region not found")
    return region.to_dict()
