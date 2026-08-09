"""FastAPI routes exposing the Feishu integration (health, minutes import, events).

Endpoints:
- GET  /api/feishu/health              - config status (no secrets)
- GET  /api/feishu/bitable/status      - Bitable config + binding counts
- POST /api/feishu/bitable/sync        - manual one-way sync of a course
- POST /api/feishu/minutes/import      - accept audio, upload + create minute (M2)
- GET  /api/feishu/minutes/{token}/status - poll transcript, store raw_text (M2)
- POST /api/feishu/events              - event subscription callback (M4)
- POST /api/feishu/card                - interactive card callback (M4)
"""

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database import DebateTopic, FeishuBinding, Student, StudentResponse, get_db

from .bot import BotService
from .client import (
    FeishuAPIError,
    FeishuClient,
    FeishuConfig,
    FeishuConfigurationError,
)
from .minutes import MinutesService
from .sync import (
    BitableSyncer,
    TABLE_KEYS,
    bitable_is_configured,
    bitable_status,
)

router = APIRouter(prefix="/api/feishu", tags=["feishu"])

UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads"
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

_feishu_config = FeishuConfig()
_client: Optional[FeishuClient] = None


def get_client() -> FeishuClient:
    global _client
    if _client is None:
        _client = FeishuClient(_feishu_config)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


@router.get("/health")
async def health():
    minute_token = os.getenv("FEISHU_MINUTE_TOKEN", "").strip()
    status = await get_client().health_check(minute_token)
    return {
        "status": status["status"],
        "feishu": _feishu_config.summary(),
        "auth": status,
        "bitable": bitable_status(_feishu_config),
    }


@router.get("/bitable/status")
def bitable_status_endpoint(db: Session = Depends(get_db)):
    """Bitable configuration and how many local entities are bound so far."""
    result = bitable_status(_feishu_config)
    counts = {}
    for key in TABLE_KEYS:
        counts[key] = (
            db.query(FeishuBinding).filter(FeishuBinding.table_key == key).count()
        )
    result["bindings"] = counts
    return result


@router.post("/bitable/sync")
async def bitable_sync(body: dict, db: Session = Depends(get_db)):
    """Manually sync one course (course + topics + students + responses)."""
    if not bitable_is_configured(_feishu_config):
        raise HTTPException(
            503,
            "FEISHU_BITABLE_APP_TOKEN / FEISHU_BITABLE_TABLE_IDS not configured",
        )
    try:
        course_id = int(body.get("course_id") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "course_id must be an integer")
    if course_id <= 0:
        raise HTTPException(400, "course_id is required")
    syncer = BitableSyncer(get_client(), _feishu_config)
    return await syncer.sync_course(db, course_id)


@router.post("/minutes/import")
async def import_minute(
    course_id: int = Form(...),
    student_id: int = Form(...),
    topic_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Step 1 of the ASR flow: accept an audio file, upload to Feishu drive,
    create a Minute, and bind it to the student's response row.

    Step 2: poll GET /api/feishu/minutes/{minute_token}/status until the
    transcript is ready (or subscribe to minutes.minute.generated_v1).
    """
    student = db.get(Student, student_id)
    topic = db.get(DebateTopic, topic_id)
    if not student or student.course_id != course_id:
        raise HTTPException(400, "student not found in course")
    if not topic or topic.course_id != course_id:
        raise HTTPException(400, "topic not found in course")
    if not _feishu_config.is_configured:
        raise HTTPException(503, "FEISHU_APP_ID / FEISHU_APP_SECRET not configured")

    original_name = os.path.basename(file.filename or "audio")
    safe_name = (
        f"{course_id}_{student_id}_{topic_id}_"
        f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{original_name}"
    )
    dest = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest, "wb") as fh:
        fh.write(await file.read())

    minutes = MinutesService(get_client())
    try:
        file_token = await minutes.upload_media(dest)
        minute = await minutes.create_minute(file_token)
    except (FeishuAPIError, FeishuConfigurationError) as exc:
        raise HTTPException(502, f"Feishu minutes import failed: {exc}")

    resp = (
        db.query(StudentResponse)
        .filter(
            StudentResponse.student_id == student_id,
            StudentResponse.topic_id == topic_id,
        )
        .first()
    )
    if resp is None:
        resp = StudentResponse(
            student_id=student_id, topic_id=topic_id, raw_text="", source="asr"
        )
        db.add(resp)
    resp.feishu_minute_id = minute["minute_token"]
    resp.source = "asr"
    db.commit()

    return {
        "minute_token": minute["minute_token"],
        "minute_url": minute.get("minute_url", ""),
        "status": "transcribing",
    }


@router.get("/minutes/{minute_token}/status")
async def minute_status(
    minute_token: str,
    db: Session = Depends(get_db),
):
    """Step 2: poll until the Minute transcript is ready, then store the
    transcript as raw_text on the bound StudentResponse."""
    if not _feishu_config.is_configured:
        raise HTTPException(503, "FEISHU_APP_ID / FEISHU_APP_SECRET not configured")

    minutes = MinutesService(get_client())
    try:
        transcript = await minutes.get_transcript(minute_token)
    except FeishuAPIError as exc:
        # Minute may still be generating - report as transcribing.
        return {"minute_token": minute_token, "status": "transcribing", "detail": str(exc)}

    if not transcript:
        return {"minute_token": minute_token, "status": "transcribing"}

    resp = (
        db.query(StudentResponse)
        .filter(StudentResponse.feishu_minute_id == minute_token)
        .first()
    )
    stored = False
    if resp and not resp.raw_text:
        resp.raw_text = transcript
        db.commit()
        stored = True

    return {
        "minute_token": minute_token,
        "status": "ready",
        "transcript_preview": transcript[:200],
        "stored": stored,
    }


@router.post("/events")
async def feishu_events(body: dict):
    """Feishu event subscription callback.

    Handles url_verification (challenge) and acknowledges other events.
    TODO(M4): dispatch im.message.receive_v1 / minutes.minute.generated_v1.
    """
    try:
        event = BotService.handle_event(_feishu_config, body)
    except ValueError as exc:
        raise HTTPException(403, str(exc))
    if "challenge" in event:
        return event
    return {"code": 0, "msg": "ack"}


@router.post("/card")
async def feishu_card(body: dict):
    """Interactive card callback (button clicks).

    TODO(M4): verify X-Lark-Signature header, then wire card buttons to the
    teacher review / comment confirm flows (see 飞书集成技术方案.md 4.3).
    """
    return {"code": 0, "msg": "ack", "received": bool(body)}
