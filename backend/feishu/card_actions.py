"""Shared dispatch for interactive-card button actions.

Both delivery channels route here so they cannot drift:
- HTTP callback: POST /api/feishu/card (feishu.routes.feishu_card)
- WebSocket long connection: card.action.trigger (feishu.ws_listener)

The input is the button's ``value`` dict; the output is the raw response dict
(e.g. {"toast": {...}}) that each channel serializes its own way (JSON body for
HTTP, P2CardActionTriggerResponse for the long connection).
"""

from typing import Callable, Optional

from sqlalchemy.orm import Session

from database import PrepPlan, StudentResponse

from .client import FeishuConfig
from .reviews import apply_teacher_review

_config = FeishuConfig()


def dispatch_card_action(
    db: Session,
    value: dict,
    schedule_sync: Optional[Callable[[int], None]] = None,
) -> dict:
    """Dispatch one card button action by its ``value["action"]`` name."""
    if not isinstance(value, dict):
        value = {}
    action_name = str(value.get("action") or "")

    if action_name == "review_confirm":
        return _card_review_confirm(db, value, schedule_sync)
    if action_name == "request_change":
        return {
            "toast": {
                "type": "info",
                "content": "请在网页端“批改”页调整评分与评语",
            }
        }
    if action_name == "send_comment":
        return _card_send_comment(value)
    if action_name == "prep_confirm":
        return _card_prep_confirm(db, value)
    return {"toast": {"type": "warning", "content": "未知操作，请升级应用"}}


def _card_review_confirm(
    db: Session, value: dict, schedule_sync: Optional[Callable[[int], None]]
) -> dict:
    """Confirm an AI review from a card button: persist review + calibration."""
    try:
        rid = int(value.get("response_id") or 0)
    except (TypeError, ValueError):
        return {"toast": {"type": "error", "content": "卡片参数无效"}}
    resp = db.get(StudentResponse, rid)
    if not resp:
        return {"toast": {"type": "error", "content": "作答记录不存在"}}

    apply_teacher_review(
        db,
        resp,
        dimension_scores=value.get("dimension_scores")
        or resp.teacher_dimension_scores
        or resp.ai_dimension_scores,
        confidence_override=value.get("confidence_override")
        or resp.teacher_confidence_override,
        tags=(
            value.get("tags")
            if value.get("tags") is not None
            else resp.teacher_tags or resp.ai_suggested_tags
        ),
        note=value.get("note")
        if value.get("note") is not None
        else resp.teacher_note
        or "",
        rating=value.get("rating") or resp.teacher_rating or "",
    )
    db.commit()
    if schedule_sync is not None:
        schedule_sync(rid)
    return {"toast": {"type": "success", "content": "评分已确认，校准记录已保存"}}


def _card_send_comment(value: dict) -> dict:
    """'Send to student' button: student accounts are not bound to Feishu yet,
    so this is honestly reported as 待联调 instead of faking success."""
    if not _config.teacher_open_id:
        return {
            "toast": {
                "type": "warning",
                "content": "待联调：尚未配置 FEISHU_TEACHER_OPEN_ID",
            }
        }
    return {
        "toast": {
            "type": "warning",
            "content": "待联调：学生暂未绑定飞书账号，评语已保存在系统中",
        }
    }


def _card_prep_confirm(db: Session, value: dict) -> dict:
    """Confirm the lesson-prep plan from a card button (teacher decision gate)."""
    try:
        cid = int(value.get("course_id") or 0)
    except (TypeError, ValueError):
        return {"toast": {"type": "error", "content": "卡片参数无效"}}
    plan = db.query(PrepPlan).filter(PrepPlan.course_id == cid).first()
    if not plan:
        return {"toast": {"type": "error", "content": "讲评计划不存在，请先在网页端生成"}}
    if not plan.lesson_plan:
        return {"toast": {"type": "warning", "content": "讲评计划还没有选辩题"}}
    plan.confirmed = True
    db.commit()
    return {"toast": {"type": "success", "content": "讲评计划已确认"}}
