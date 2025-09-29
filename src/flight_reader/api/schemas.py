from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PointSchema(BaseModel):
    lat: float
    lon: float


class OperatorSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class UavTypeSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    description: Optional[str]


class RegionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class FlightSchema(BaseModel):
    id: int
    flight_id: str
    takeoff_time: Optional[datetime]
    landing_time: Optional[datetime]
    duration_seconds: Optional[float]
    operator: Optional[OperatorSchema]
    uav_type: Optional[UavTypeSchema]
    region_from: Optional[RegionSchema]
    region_to: Optional[RegionSchema]
    takeoff_point: Optional[PointSchema]
    landing_point: Optional[PointSchema]
    raw_message_id: Optional[int]


class FlightFilterSchema(BaseModel):
    operator_id: Optional[int] = None
    uav_type_id: Optional[int] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class FlightStatsRegionSchema(BaseModel):
    code: str
    name: str
    flight_count: int


class FlightStatsSchema(BaseModel):
    total_flights: int
    regions: list[FlightStatsRegionSchema]
