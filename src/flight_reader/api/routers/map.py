"""Map-related API stubs."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

# Placeholder dataset; replace with DB integration later.
REGION_STUB = [
    {
        "path": "m 130.24729,259.26463 -0.71301,-1.3323 -0.83965,1.13893 -1.20312,0.61639 -0.3652,1.98343 -2.7566,-1.20341 -1.29507,1.2557 -1.79887,-1.96928 -0.51738,2.08913 -1.70104,0.51357 0.48353,2.36036 1.41813,-1.06374 1.07846,1.34199 2.31013,-0.11587 0.63117,-1.4221 0.77636,1.28888 1.63087,-0.86752 1.60105,1.08107 2.52028,-0.21377 0.38854,-1.63667 -0.76508,-2.45949 0.30997,-0.96605 c -0.75062,0.0982 -0.83803,-0.13605 -1.19347,-0.41925 z",
        "title": "Москва",
        "code": "RU-MOW",
    },
    {
        "path": "m 145.10293,240.55829 -0.20448,-0.92763 -1.25631,0.50222 -0.83441,1.15479 0.33609,2.17817 1.90543,0.47269 0.92514,-1.35137 0.8016,-0.17812 -0.35543,-1.85075 -0.32163,-0.44799 z",
        "title": "Санкт-Петербург",
        "code": "RU-SPE",
    },
]


@router.get("/map/regions")
def list_regions(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    stat_type: Literal["flights", "delays", "cargo", "all"] | None = Query(
        default=None
    ),
    direction: Literal["domestic", "international", "all"] | None = Query(default=None),
):
    """Возвращает харкодно список регионов с path и code региона, параметры пока не используются"""
    _ = (date_from, date_to, stat_type, direction)
    return REGION_STUB


@router.get("/map/regions/{code}")
def get_region(code: str):
    """Детали по определенному региону"""
    for region in REGION_STUB:
        if region["code"].lower() == code.lower():
            return region
    raise HTTPException(status_code=404, detail="Region not found")
