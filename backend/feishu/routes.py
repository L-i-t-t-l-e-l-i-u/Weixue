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

import hashlib
import hmac
import json
import os
from datetime import datetime
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from sqlalchemy.orm import Session

from database import (
    CompanionTurn,
    DebateTopic,
    FeishuBinding,
    SessionLocal,
    Student,
    StudentResponse,
    get_db,
)

from .bot import BotService
from .card_actions import dispatch_card_action
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


async def _sync_response_after_review(response_id: int) -> None:
    """Fire-and-forget Bitable sync after a card callback confirms a review."""
    db = SessionLocal()
    try:
        syncer = BitableSyncer(get_client(), _feishu_config)
        if syncer.available:
            await syncer.sync_response(db, response_id)
    except Exception:
        # Sync failures are reported via /api/feishu/bitable/status only.
        pass
    finally:
        db.close()


def _verify_event_signature(
    raw_body: bytes, timestamp: str, nonce: str, signature: str
) -> bool:
    """sha256(timestamp + nonce + encrypt_key + raw_body) per official docs."""
    bs = (
        f"{timestamp}{nonce}{_feishu_config.encrypt_key}".encode("utf-8")
        + raw_body
    )
    return hmac.compare_digest(hashlib.sha256(bs).hexdigest(), signature or "")


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
        # 与 import_text/import_audio 一致：首轮发言也要进对话轮次，
        # 否则评估/时间线/学生端轮询都会丢掉第一轮。
        if not any(t.role == "student" for t in (resp.companion_turns or [])):
            db.add(
                CompanionTurn(
                    response_id=resp.id,
                    role="student",
                    content=transcript,
                    turn_type="",
                )
            )
        db.commit()
        stored = True

    return {
        "minute_token": minute_token,
        "status": "ready",
        "transcript_preview": transcript[:200],
        "stored": stored,
    }


@router.post("/events")
async def feishu_events(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Feishu event subscription callback.

    Handles url_verification (challenge), verifies the X-Lark-Signature when an
    Encrypt Key is configured, and dispatches im.message.receive_v1 to the bot.
    """
    raw_body = await request.body()
    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")
    if _feishu_config.encrypt_key and signature and not _verify_event_signature(
        raw_body, timestamp, nonce, signature
    ):
        raise HTTPException(401, "invalid event signature")
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(400, "invalid event body")
    try:
        event = BotService.handle_event(_feishu_config, body)
    except ValueError as exc:
        raise HTTPException(403, str(exc))
    if "challenge" in event:
        return event
    if event.get("type") == "im.message.receive_v1":
        payload = event.get("event") or {}
        message = payload.get("message") or {}
        message_id = message.get("message_id", "")
        msg_type = message.get("message_type", "")
        text = ""
        if msg_type == "text":
            try:
                text = json.loads(message.get("content", "{}")).get("text", "")
            except (TypeError, ValueError):
                text = ""
        if message_id and ("评语" in text or "帮助" in text):
            background_tasks.add_task(_reply_bot_help, message_id)
    return {"code": 0, "msg": "ack"}


async def _reply_bot_help(message_id: str) -> None:
    """Lightweight im.message.receive_v1 dispatch: answer help-ish messages."""
    try:
        bot = BotService(get_client())
        await bot.reply_text(
            message_id,
            "思辨星机器人：教师可在网页端生成评语后由机器人推送确认卡片；"
            "如需帮助请联调群内说明。",
        )
    except Exception:
        pass


@router.post("/card")
async def feishu_card(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Interactive card callback (button clicks).

    Verifies `X-Lark-Signature` (sha1 over timestamp + nonce + verification
    token + raw body), decrypts when Encrypt Key is configured, checks the
    callback `header.token`, then delegates to the shared dispatcher (also used
    by the WebSocket long-connection listener in feishu.ws_listener).
    """
    raw_body = await request.body()
    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")
    if not BotService.verify_card_signature(
        _feishu_config, raw_body, timestamp, nonce, signature
    ):
        raise HTTPException(401, "invalid card callback signature")
    try:
        plaintext = BotService.decrypt_card_payload(_feishu_config, raw_body)
        payload = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(400, str(exc))

    header = payload.get("header") or {}
    if (
        _feishu_config.verification_token
        and header.get("token") != _feishu_config.verification_token
    ):
        raise HTTPException(403, "card callback token mismatch")

    event = payload.get("event") or {}
    action = event.get("action") or {}
    value = action.get("value") or {}
    return dispatch_card_action(
        db,
        value,
        schedule_sync=lambda rid: background_tasks.add_task(
            _sync_response_after_review, rid
        ),
    )
