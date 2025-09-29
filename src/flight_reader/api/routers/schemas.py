from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class MonthlyFlightsSchema(BaseModel):
    month: datetime
    flights_count: int


class DurationMetricsSchema(BaseModel):
    month: Optional[datetime] = None
    region_name: Optional[str] = None
    avg_duration_min: float


class RegionFlightsSchema(BaseModel):
    region_name: str
    flights_count: int


class PeakLoadSchema(BaseModel):
    peak_flights_per_hour: int


class DailyDynamicsSchema(BaseModel):
    hour_of_day: int
    avg_flights: float
    median_flights: float


class MonthlyGrowthSchema(BaseModel):
    month: datetime
    flights_count: int
    prev_month_count: Optional[int] = None
    growth_percent: Optional[float] = None


class FlightDensitySchema(BaseModel):
    region_name: str
    flights_count: int
    area_km2: float
    flights_per_1000km2: float


class DailyActivitySchema(BaseModel):
    hour: int
    flights_count: int
    time_of_day: str


class ZeroActivitySchema(BaseModel):
    region_name: str
    zero_activity_days: int
    active_days: int
    total_days_in_period: int