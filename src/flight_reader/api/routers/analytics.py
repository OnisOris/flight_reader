from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, extract, text
from sqlalchemy.orm import Session

from flight_reader.api.schemas import (
    MonthlyFlightsSchema,
    DurationMetricsSchema,
    RegionFlightsSchema,
    PeakLoadSchema,
    DailyDynamicsSchema,
    MonthlyGrowthSchema,
    FlightDensitySchema,
    DailyActivitySchema,
    ZeroActivitySchema
)
from flight_reader.db import get_session
from flight_reader.db_models import Flight, Region

router = APIRouter()


@router.get("/metrics/monthly-flights", response_model=List[MonthlyFlightsSchema])
def get_monthly_flights(
    session: Session = Depends(get_session),
) -> List[MonthlyFlightsSchema]:
    """Число полетов в месяц"""
    
    result = session.query(
        func.date_trunc('month', Flight.takeoff_time).label('month'),
        func.count().label('flights_count')
    ).group_by(
        func.date_trunc('month', Flight.takeoff_time)
    ).order_by('month').all()
    
    return [
        MonthlyFlightsSchema(
            month=row.month,
            flights_count=row.flights_count
        ) for row in result
    ]


@router.get("/metrics/avg-duration-monthly", response_model=List[DurationMetricsSchema])
def get_avg_duration_monthly(
    session: Session = Depends(get_session),
) -> List[DurationMetricsSchema]:
    """Средняя длительность полетов по месяцам"""
    
    result = session.query(
        func.date_trunc('month', Flight.takeoff_time).label('month'),
        func.avg(Flight.duration).label('avg_duration_min')
    ).group_by(
        func.date_trunc('month', Flight.takeoff_time)
    ).order_by('month').all()
    
    return [
        DurationMetricsSchema(
            month=row.month,
            avg_duration_min=float(row.avg_duration_min) if row.avg_duration_min else 0
        ) for row in result
    ]


@router.get("/metrics/avg-duration-regions", response_model=List[DurationMetricsSchema])
def get_avg_duration_regions(
    session: Session = Depends(get_session),
) -> List[DurationMetricsSchema]:
    """Средняя длительность полетов по регионам"""
    
    result = session.query(
        Region.name.label('region_name'),
        func.avg(Flight.duration).label('avg_duration_min')
    ).join(
        Flight, Flight.region_from_id == Region.id
    ).group_by(
        Region.name
    ).all()
    
    return [
        DurationMetricsSchema(
            region_name=row.region_name,
            avg_duration_min=float(row.avg_duration_min) if row.avg_duration_min else 0
        ) for row in result
    ]


@router.get("/metrics/top-regions", response_model=List[RegionFlightsSchema])
def get_top_regions(
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> List[RegionFlightsSchema]:
    """Топ-N регионов по количеству полетов"""
    
    result = session.query(
        Region.name.label('region_name'),
        func.count().label('flights_count')
    ).join(
        Flight, Flight.region_from_id == Region.id
    ).group_by(
        Region.name
    ).order_by(
        func.count().desc()
    ).limit(limit).all()
    
    return [
        RegionFlightsSchema(
            region_name=row.region_name,
            flights_count=row.flights_count
        ) for row in result
    ]


@router.get("/metrics/peak-load", response_model=PeakLoadSchema)
def get_peak_load(
    session: Session = Depends(get_session),
) -> PeakLoadSchema:
    """Пиковая нагрузка (максимум полетов за час)"""
    
    subquery = session.query(
        func.date_trunc('hour', Flight.takeoff_time).label('hour'),
        func.count().label('hourly_count')
    ).group_by(
        func.date_trunc('hour', Flight.takeoff_time)
    ).subquery()
    
    result = session.query(
        func.max(subquery.c.hourly_count).label('peak_flights_per_hour')
    ).scalar()
    
    return PeakLoadSchema(peak_flights_per_hour=result or 0)


# @router.get("/metrics/daily-dynamics", response_model=List[DailyDynamicsSchema])
# def get_daily_dynamics(
#     session: Session = Depends(get_session),
# ) -> List[DailyDynamicsSchema]:
#     """Среднесуточная динамика по часам"""
    
#     # Используем text() для сложного SQL с оконными функциями
#     query = text("""
#         SELECT 
#             hour_of_day,
#             AVG(daily_count) AS avg_flights,
#             PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY daily_count) AS median_flights
#         FROM (
#             SELECT 
#                 DATE(takeoff_time) AS day,
#                 EXTRACT(HOUR FROM takeoff_time) AS hour_of_day,
#                 COUNT(*) AS daily_count
#             FROM flights
#             GROUP BY day, hour_of_day
#         ) AS daily_hourly
#         GROUP BY hour_of_day
#         ORDER BY hour_of_day;
#     """)
    
#     result = session.execute(query).fetchall()
    
#     return [
#         DailyDynamicsSchema(
#             hour_of_day=int(row.hour_of_day),
#             avg_flights=float(row.avg_flights) if row.avg_flights else 0,
#             median_flights=float(row.median_flights) if row.median_flights else 0
#         ) for row in result
#     ]


@router.get("/metrics/monthly-growth", response_model=List[MonthlyGrowthSchema])
def get_monthly_growth(
    session: Session = Depends(get_session),
) -> List[MonthlyGrowthSchema]:
    """Рост/падение числа полетов по месяцам"""
    
    query = text("""
        WITH monthly AS (
            SELECT 
                DATE_TRUNC('month', takeoff_time) AS month,
                COUNT(*) AS flights_count
            FROM flights
            GROUP BY month
        ),
        growth_calc AS (
            SELECT 
                month,
                flights_count,
                LAG(flights_count) OVER (ORDER BY month) AS prev_month_count
            FROM monthly
        )
        SELECT 
            month,
            flights_count,
            prev_month_count,
            CASE
                WHEN prev_month_count IS NULL THEN NULL
                ELSE ROUND(
                    (flights_count - prev_month_count) * 100.0 / prev_month_count,
                    1
                )
            END AS growth_percent
        FROM growth_calc
        ORDER BY month;
    """)
    
    result = session.execute(query).fetchall()
    
    return [
        MonthlyGrowthSchema(
            month=row.month,
            flights_count=row.flights_count,
            prev_month_count=row.prev_month_count,
            growth_percent=float(row.growth_percent) if row.growth_percent is not None else None
        ) for row in result
    ]


# @router.get("/metrics/flight-density", response_model=List[FlightDensitySchema])
# def get_flight_density(
#     session: Session = Depends(get_session),
# ) -> List[FlightDensitySchema]:
#     """Плотность полетов по регионам"""
    
#     result = session.query(
#         Region.name.label('region_name'),
#         func.count().label('flights_count'),
#         Region.area_km2,
#         (func.count() / (Region.area_km2 / 1000.0)).label('flights_per_1000km2')
#     ).join(
#         Flight, Flight.region_from_id == Region.id
#     ).group_by(
#         Region.name, Region.area_km2
#     ).all()
    
#     return [
#         FlightDensitySchema(
#             region_name=row.region_name,
#             flights_count=row.flights_count,
#             area_km2=float(row.area_km2) if row.area_km2 else 0,
#             flights_per_1000km2=float(row.flights_per_1000km2) if row.flights_per_1000km2 else 0
#         ) for row in result
#     ]


@router.get("/metrics/daily-activity", response_model=List[DailyActivitySchema])
def get_daily_activity(
    session: Session = Depends(get_session),
) -> List[DailyActivitySchema]:
    """Дневная активность по часам"""
    
    result = session.query(
        extract('hour', Flight.takeoff_time).label('hour'),
        func.count().label('flights_count'),
        func.case(
            (extract('hour', Flight.takeoff_time).between(5, 11), 'Утро'),
            (extract('hour', Flight.takeoff_time).between(12, 17), 'День'),
            else_='Вечер/Ночь'
        ).label('time_of_day')
    ).group_by(
        'hour', 'time_of_day'
    ).order_by('hour').all()
    
    return [
        DailyActivitySchema(
            hour=int(row.hour),
            flights_count=row.flights_count,
            time_of_day=row.time_of_day
        ) for row in result
    ]


# @router.get("/metrics/zero-activity-days", response_model=List[ZeroActivitySchema])
# def get_zero_activity_days(
#     session: Session = Depends(get_session),
# ) -> List[ZeroActivitySchema]:
#     """Дни без полетов по регионам (оптимизированная версия)"""
    
    # query = text("""
    #     WITH period_days AS (
    #         SELECT 
    #             MAX(DATE(takeoff_time)) as max_date,
    #             MIN(DATE(takeoff_time)) as min_date,
    #             MAX(DATE(takeoff_time)) - MIN(DATE(takeoff_time)) + 1 as total_days
    #         FROM flights
    #     ),
    #     region_active_days AS (
    #         SELECT 
    #             r.name AS region_name,
    #             COUNT(DISTINCT DATE(f.takeoff_time)) AS active_days
    #         FROM flights f
    #         JOIN regions r ON f.region_from_id = r.id
    #         GROUP BY r.name
    #     )
    #     SELECT 
    #         ra.region_name,
    #         p.total_days - ra.active_days AS zero_activity_days,
    #         ra.active_days AS active_days,
    #         p.total_days AS total_days_in_period
    #     FROM region_active_days ra
    #     CROSS JOIN period_days p
    #     ORDER BY zero_activity_days DESC;
    # """)
    
    # result = session.execute(query).fetchall()
    
#     return [
#         ZeroActivitySchema(
#             region_name=row.region_name,
#             zero_activity_days=row.zero_activity_days,
#             active_days=row.active_days,
#             total_days_in_period=row.total_days_in_period
#         ) for row in result
#     ]