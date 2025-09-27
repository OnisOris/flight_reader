from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from geoalchemy2 import WKTElement
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from flight_reader.db import SessionLocal
from flight_reader.db_models import (
    Flight,
    Operator,
    RawMessage,
    UavType,
    UploadLog,
    User,
)
from parser.parser import ShrRecord, ShrParser

logger = logging.getLogger(__name__)


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

        cache = _ReferenceCache()
        success_count = 0
        errors: List[str] = []

        for record in records:
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

    flight = Flight(
        flight_id=flight_id,
        operator_id=operator.id,
        uav_type_id=uav_type.id,
        takeoff_time=takeoff_time,
        landing_time=landing_time,
        duration=duration,
        geom_takeoff=_parse_coordinate(_first_field(fields, "DEP")),
        geom_landing=_parse_coordinate(_first_field(fields, "DEST")),
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
    value = _first_field(fields, "DOF")
    if value and re.fullmatch(r"\d{6}", value):
        return datetime.strptime(value, "%y%m%d").date()
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
