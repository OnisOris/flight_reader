"""Загрузка SHR-файлов и импорт в базу данных."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Iterable, List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from sqlalchemy.orm import Session

from flight_reader.db import get_session
from flight_reader.db_models import UploadLog
from flight_reader.api.schemas import UploadStatusSchema
from flight_reader.services.import_shr import process_shr_upload, validate_user

router = APIRouter()


@router.post("/uploads/shr")
async def upload_shr(
    background_tasks: BackgroundTasks,
    user_id: Annotated[int, Form(...)],
    file: UploadFile = File(...),
    sheet: Annotated[Optional[List[str]], Form()] = None,
    session: Session = Depends(get_session),
):
    """Принимает XLSX-файл, планирует парсинг и загрузку данных."""

    try:
        validate_user(session, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=".xlsx")
    tmp_path = Path(tmp_path_str)
    with os.fdopen(tmp_fd, "wb") as tmp_file:
        shutil.copyfileobj(file.file, tmp_file)
    await file.close()

    upload_log = UploadLog(
        user_id=user_id,
        source_file=file.filename,
        status="PENDING",
    )
    session.add(upload_log)
    session.commit()

    sheet_names: Optional[Iterable[str]] = tuple(sheet) if sheet else None

    background_tasks.add_task(
        process_shr_upload,
        upload_log.id,
        tmp_path,
        sheet_names,
    )

    return {
        "upload_id": upload_log.id,
        "status": "QUEUED",
        "status_check": f"/api/uploads/{upload_log.id}",
    }


@router.get("/uploads/{upload_id}", response_model=UploadStatusSchema)
def get_upload_status(upload_id: int, session: Session = Depends(get_session)) -> UploadStatusSchema:
    """Возвращает текущий статус загрузки SHR."""

    upload_log = session.get(UploadLog, upload_id)
    if upload_log is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    return UploadStatusSchema.model_validate(upload_log)
