from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import date, datetime, time, timezone, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from geoalchemy2 import WKTElement
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from flight_reader.db import SessionLocal
from flight_reader.db_models import (
    Flight,
    Operator,
    RawMessage,
    Region,
    UavType,
    UploadLog,
    User,
)
from parser.parser import ShrMessage, ShrRecord, ShrParser

logger = logging.getLogger(__name__)

_PROGRESS_UPDATE_STEP = 500
_PROGRESS_UPDATE_SECONDS = 10.0
_PROGRESS_LOG_STEP = 2000


class _ReferenceCache:
    def __init__(self) -> None:
        self.operators: Dict[str, Operator] = {}
        self.uav_types: Dict[str, UavType] = {}


def process_shr_upload(
    upload_log_id: int,
    file_path: Path,
    sheet_names: Optional[Iterable[str]] = None,
) -> None:
    session = SessionLocal()
    try:
        upload_log = session.get(UploadLog, upload_log_id)
        if upload_log is None:
            logger.error("Upload log %s not found", upload_log_id)
            return
        upload_log.status = "PROCESSING"
        session.commit()

        parser = ShrParser(file_path, sheet_names=sheet_names)
        records = parser.parse()
        total_records = len(records)

        cache = _ReferenceCache()
        success_count = 0
        errors: List[str] = []
        last_progress_update = time.monotonic()

        for index, record in enumerate(records, start=1):
            try:
                created = _persist_record(session, record, cache)
                session.commit()
                if created:
                    success_count += 1
            except IntegrityError as exc:  # duplicate or constraint failure
                session.rollback()
                logger.info("Duplicate flight skipped: sheet=%s row=%s", record.sheet, record.row_index)
                errors.append(
                    f"Row {record.row_index} ({record.sheet}): duplicate flight ({exc.orig})"
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                session.rollback()
                logger.exception("Failed to import record sheet=%s row=%s", record.sheet, record.row_index)
                errors.append(f"Row {record.row_index} ({record.sheet}): {exc}")
                continue

            now = time.monotonic()
            should_update_progress = False
            if index % _PROGRESS_UPDATE_STEP == 0:
                should_update_progress = True
            elif now - last_progress_update >= _PROGRESS_UPDATE_SECONDS:
                should_update_progress = True

            if should_update_progress:
                upload_log = session.get(UploadLog, upload_log_id)
                if upload_log is None:
                    logger.error("Upload log %s disappeared during processing", upload_log_id)
                    return
                _update_upload_progress(upload_log, success_count, index, total_records)
                session.commit()
                last_progress_update = now

            if index % _PROGRESS_LOG_STEP == 0:
                logger.info(
                    "Upload %s progress: processed %s/%s records (flights added: %s)",
                    upload_log_id,
                    index,
                    total_records,
                    success_count,
                )

        upload_log = session.get(UploadLog, upload_log_id)
        if upload_log is None:
            logger.error("Upload log %s disappeared during processing", upload_log_id)
            return

        upload_log.flight_count = success_count
        if errors:
            upload_log.status = "PARTIAL_SUCCESS" if success_count else "ERROR"
            upload_log.details = "\n".join(errors[:20])
        else:
            upload_log.status = "SUCCESS"
            upload_log.details = None
        session.commit()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        session.rollback()
        logger.exception("Unexpected failure while processing upload %s", upload_log_id)
        upload_log = session.get(UploadLog, upload_log_id)
        if upload_log is not None:
            upload_log.status = "ERROR"
            upload_log.details = str(exc)
            session.commit()
    finally:
        session.close()
        try:
            file_path.unlink()
        except FileNotFoundError:
            pass


_COORD_RE = re.compile(
    r"^(?P<lat>\d{4,6})(?P<lat_dir>[NS])(?P<lon>\d{5,7})(?P<lon_dir>[EW])$"
)

_COORD_INLINE_RE = re.compile(r"\d{4,6}[NS]\d{5,7}[EW]")


def _parse_coordinate(value: Optional[str]) -> Optional[WKTElement]:
    if not value:
        return None
    normalized = value.strip().replace(" ", "")
    match = _COORD_RE.match(normalized)
    if not match:
        return None

    lat = _to_decimal(match.group("lat"), match.group("lat_dir"), is_lat=True)
    lon = _to_decimal(match.group("lon"), match.group("lon_dir"), is_lat=False)
    if lat is None or lon is None:
        return None
    point = f"POINT({lon} {lat})"
    return WKTElement(point, srid=4326)


def _to_decimal(raw: str, direction: str, *, is_lat: bool) -> Optional[float]:
    if is_lat:
        deg_len = 2
    else:
        deg_len = 3
    if len(raw) < deg_len + 2:
        return None
    degrees = int(raw[:deg_len])
    remainder = raw[deg_len:]
    if len(remainder) == 2:
        minutes = int(remainder)
        seconds = 0
    elif len(remainder) == 4:
        minutes = int(remainder[:2])
        seconds = int(remainder[2:])
    else:
        minutes = int(remainder[:-2])
        seconds = int(remainder[-2:])
    decimal = degrees + minutes / 60 + seconds / 3600
    if direction in {"S", "W"}:
        decimal = -decimal
    return decimal


def _extract_message_points(message: ShrMessage) -> List[WKTElement]:
    points: List[WKTElement] = []
    seen: set[str] = set()
    for match in _COORD_INLINE_RE.findall(message.raw):
        geom = _parse_coordinate(match)
        if geom is None:
            continue
        key = getattr(geom, "desc", str(geom))
        if key in seen:
            continue
        seen.add(key)
        points.append(geom)
    return points


def _detect_region_id(
    session: Session,
    primary: Optional[WKTElement],
    fallbacks: Iterable[WKTElement],
    region_hint: Optional[str],
) -> Optional[int]:
    candidate_geoms: List[WKTElement] = []
    seen: set[str] = set()
    if primary is not None:
        key = getattr(primary, "desc", str(primary))
        seen.add(key)
        candidate_geoms.append(primary)
    for geom in fallbacks:
        if geom is None:
            continue
        key = getattr(geom, "desc", str(geom))
        if key in seen:
            continue
        seen.add(key)
        candidate_geoms.append(geom)

    for geom in candidate_geoms:
        stmt = select(Region.id).where(func.ST_Contains(Region.geom, geom)).limit(1)
        region_id = session.execute(stmt).scalar_one_or_none()
        if region_id is not None:
            return region_id

    if region_hint:
        region_id = _find_region_by_hint(session, region_hint)
        if region_id is not None:
            return region_id

    return None


def _update_upload_progress(
    upload_log: UploadLog,
    success_count: int,
    processed: int,
    total: int,
) -> None:
    upload_log.flight_count = success_count
    if total:
        upload_log.details = f"Processed {processed}/{total} records"
    else:
        upload_log.details = f"Processed {processed} records"


def _find_region_by_hint(session: Session, hint: str) -> Optional[int]:
    if not hint:
        return None
    normalized = hint.strip()
    if not normalized:
        return None
    candidates = {normalized}
    lower = normalized.lower()
    suffixes = ["ский", "ская", "ское", "ские", "ской", "ских", "скому", "скую", "ского"]
    for suffix in suffixes:
        if lower.endswith(suffix):
            stripped = normalized[: -len(suffix)].strip()
            if stripped:
                candidates.add(stripped)
    candidates.update({c.lower() for c in list(candidates)})

    for candidate in candidates:
        candidate_clean = candidate.strip().lower()
        if not candidate_clean:
            continue
        like_pattern = f"%{candidate_clean}%"
        stmt = (
            select(Region.id)
            .where(func.lower(Region.name).like(like_pattern))
            .order_by(Region.id)
            .limit(1)
        )
        region_id = session.execute(stmt).scalar_one_or_none()
        if region_id is not None:
            return region_id
    return None


def _persist_record(session: Session, record: ShrRecord, cache: _ReferenceCache) -> bool:
    message = record.message
    fields = message.fields

    operator_value = _first_field(fields, "OPR") or "UNKNOWN"
    uav_type_value = _first_field(fields, "TYP") or "UNKNOWN"

    operator = _ensure_operator(session, operator_value, cache)
    uav_type = _ensure_uav_type(session, uav_type_value, cache)

    raw_message = RawMessage(content=message.raw, sender=None)
    session.add(raw_message)
    session.flush()  # ensures raw_message.id

    flight_id_raw = (
        _first_field(fields, "SID")
        or _first_field(fields, "REG")
        or message.addressee
        or f"SHR-{record.sheet}-{record.row_index}"
    )
    flight_id = _normalize_identifier(flight_id_raw, max_length=64)

    dof_date = _parse_dof(fields)
    base_date = _resolve_record_date(record) or dof_date
    takeoff_time = _combine_date_time(base_date, message.valid_from)
    landing_time = _combine_date_time(base_date, message.valid_to)

    if takeoff_time and landing_time and landing_time < takeoff_time:
        landing_time = None

    duration = None
    if takeoff_time and landing_time:
        duration = landing_time - takeoff_time

    geom_takeoff = _parse_coordinate(_first_field(fields, "DEP"))
    geom_landing = _parse_coordinate(_first_field(fields, "DEST"))

    additional_points = _extract_message_points(message)
    region_from_id = _detect_region_id(
        session,
        geom_takeoff,
        additional_points,
        record.region_hint,
    )
    region_to_id = _detect_region_id(
        session,
        geom_landing,
        additional_points,
        record.region_hint,
    )

    if region_from_id is None and region_to_id is not None:
        region_from_id = region_to_id
    if region_to_id is None and region_from_id is not None:
        region_to_id = region_from_id

    flight = Flight(
        flight_id=flight_id,
        operator_id=operator.id,
        uav_type_id=uav_type.id,
        takeoff_time=takeoff_time,
        landing_time=landing_time,
        duration=duration,
        geom_takeoff=geom_takeoff,
        geom_landing=geom_landing,
        region_from_id=region_from_id,
        region_to_id=region_to_id,
        raw_msg_id=raw_message.id,
    )
    session.add(flight)
    session.flush()
    return True


def _first_field(fields: Dict[str, List[str]], key: str) -> Optional[str]:
    values = fields.get(key)
    if not values:
        return None
    return values[0].strip() if isinstance(values[0], str) else values[0]


def _ensure_operator(session: Session, value: str, cache: _ReferenceCache) -> Operator:
    code = _slug_code(value) or "UNKNOWN"
    if code in cache.operators:
        return cache.operators[code]
    stmt = select(Operator).where(Operator.code == code)
    operator = session.execute(stmt).scalar_one_or_none()
    if operator is None:
        operator = Operator(code=code[:32], name=value[:255])
        session.add(operator)
        session.flush()
    cache.operators[code] = operator
    return operator


def _ensure_uav_type(session: Session, value: str, cache: _ReferenceCache) -> UavType:
    code = _slug_code(value) or "UNKNOWN"
    if code in cache.uav_types:
        return cache.uav_types[code]
    stmt = select(UavType).where(UavType.code == code)
    uav_type = session.execute(stmt).scalar_one_or_none()
    if uav_type is None:
        uav_type = UavType(code=code[:64], description=value[:255])
        session.add(uav_type)
        session.flush()
    cache.uav_types[code] = uav_type
    return uav_type


def _slug_code(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip().upper()
    slug = re.sub(r"[^A-Z0-9]+", "_", normalized)
    return slug.strip("_")[:64]


def _parse_dof(fields: Dict[str, List[str]]) -> Optional[date]:
    raw_value = _first_field(fields, "DOF")
    if not raw_value:
        return None
    match = re.search(r"\d{6}", raw_value)
    if not match:
        return None
    digits = match.group(0)
    yy = digits[:2]
    mm = digits[2:4]
    dd = digits[4:]

    def _try_parse(candidate: str) -> Optional[date]:
        try:
            return datetime.strptime(candidate, "%y%m%d").date()
        except ValueError:
            return None

    parsed = _try_parse(digits)
    if parsed is not None:
        return parsed

    # Some legacy records flip month/day (e.g., 241301 -> 240113)
    if 1 <= int(dd) <= 12 and 1 <= int(mm) <= 31:
        swapped = f"{yy}{dd}{mm}"
        parsed = _try_parse(swapped)
        if parsed is not None:
            logger.warning("Interpreted DOF %s as %s due to swapped month/day", raw_value, parsed)
            return parsed

    logger.warning("Could not parse DOF value %s", raw_value)
    return None


def _resolve_record_date(record: ShrRecord) -> Optional[date]:
    if record.flight_date is None:
        return None
    flight_date = record.flight_date
    if isinstance(flight_date, datetime):
        return flight_date.date()
    if hasattr(flight_date, "to_pydatetime"):
        return flight_date.to_pydatetime().date()
    if hasattr(flight_date, "date"):
        return flight_date.date()
    return None


def _combine_date_time(base_date: Optional[date], code: Optional[str]) -> Optional[datetime]:
    if base_date is None or not code or len(code) < 4:
        return None
    time_part = code[-4:]
    if not time_part.isdigit():
        return None
    hour = int(time_part[:2])
    minute = int(time_part[2:])
    if hour == 24 and minute == 0:
        return datetime.combine(base_date + timedelta(days=1), time(0, 0, tzinfo=timezone.utc))
    if hour > 23 or minute > 59:
        logger.warning("Skipping invalid time code %s for date %s", code, base_date)
        return None
    return datetime.combine(base_date, time(hour, minute, tzinfo=timezone.utc))


def validate_user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")
    return user


def _normalize_identifier(value: str, *, max_length: int) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized:
        normalized = "UNKNOWN"
    if len(normalized) <= max_length:
        return normalized
    hash_suffix = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]
    truncated = normalized[: max_length - 9].rstrip()
    return f"{truncated}#{hash_suffix}"
