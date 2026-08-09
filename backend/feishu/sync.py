"""One-way sync of local assessment data into Feishu Bitable (多维表格).

Design (MVP, 单向同步):
- Local SQLite is the single source of truth; Bitable is a display/review
  surface only.
- ``FeishuBinding`` stores the local entity -> remote record_id mapping so
  that repeated syncs use batch_update instead of creating duplicates.
- Every sync is guarded: missing credentials or API errors never break the
  assessment flow. Failures are reported in the returned summary and are
  visible via GET /api/feishu/bitable/status.

Feishu console prerequisites (build these tables before first sync):
- 4 tables named courses / topics / students / responses with the field
  schemas from feishu/bitable.py.
- Single-select options that must exist before write:
  * 来源: 手动录入 / 音频转写
  * 认知梯段: 基础层 / 发展层 / 进阶层
  * 类型: 两难 / 事实观点 / 因果
  * AI置信度: 高 / 低 / 不确定
  * 状态: 待评估 / AI已评 / 教师已审
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from database import (
    Course,
    FeishuBinding,
    Student,
    StudentResponse,
)

from .bitable import BitableService
from .client import FeishuClient, FeishuConfig

TABLE_KEYS = ("courses", "topics", "students", "responses")
ENTITY_TYPE_BY_TABLE = {
    "courses": "course",
    "topics": "topic",
    "students": "student",
    "responses": "response",
}

_SOURCE_LABELS = {"manual": "手动录入", "asr": "音频转写"}
_TIER_LABELS = {"basic": "基础层", "developing": "发展层", "advancing": "进阶层"}
_TYPE_LABELS = {"dilemma": "两难", "fact_opinion": "事实观点", "causal": "因果"}
_CONFIDENCE_LABELS = {
    "certain_good": "高",
    "certain_weak": "低",
    "uncertain": "不确定",
}
_STATUS_LABELS = {"pending": "待评估", "assessed": "AI已评", "reviewed": "教师已审"}


# ── Pure record builders (testable without a Feishu connection) ─────────

def _single(value: str) -> dict:
    return {"text": str(value)}


def _multi(values) -> list[dict]:
    return [{"text": str(v)} for v in (values or []) if v]


def _ms(dt) -> int:
    if not dt:
        dt = datetime.utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _format_scores(scores) -> str:
    if not scores:
        return ""
    return "；".join(f"{k}:{v}" for k, v in scores.items())


def build_course_record(course) -> dict:
    return {
        "fields": {
            "班级名": course.class_name,
            "年级": course.grade_level,
            "创建时间": _ms(course.created_at),
        }
    }


def build_topic_record(topic) -> dict:
    return {
        "fields": {
            "标题": topic.title,
            "类型": _single(_TYPE_LABELS.get(topic.topic_type, topic.topic_type or "")),
            "认知梯段": _single(
                _TIER_LABELS.get(topic.cognitive_tier or "", topic.cognitive_tier or "")
            ),
            "引导材料": topic.stimulus_material or "",
            "参考论据": "\n".join(topic.reference_arguments or []),
            "顺序": topic.order or 0,
        }
    }


def build_student_record(student) -> dict:
    return {
        "fields": {
            "姓名": student.name,
            "年级": student.grade,
            "认知梯段": _single(_TIER_LABELS.get(student.cognitive_tier, student.cognitive_tier)),
            "班级": student.course.class_name if student.course else "",
            "评语草稿": student.comment_draft or "",
        }
    }


def build_response_record(response, student, topic) -> dict:
    if response.teacher_reviewed:
        status = _STATUS_LABELS["reviewed"]
    elif response.ai_dimension_scores:
        status = _STATUS_LABELS["assessed"]
    else:
        status = _STATUS_LABELS["pending"]
    source = _SOURCE_LABELS.get(response.source or "", response.source or "手动录入")
    confidence = _CONFIDENCE_LABELS.get(
        response.ai_confidence or "", response.ai_confidence or "不确定"
    )
    return {
        "fields": {
            "学生": student.name,
            "辩题": topic.title,
            "来源": _single(source),
            "原始文本": response.raw_text or "",
            "清洗文本": response.cleaned_text or "",
            "AI评分摘要": _format_scores(response.ai_dimension_scores),
            "AI置信度": _single(confidence),
            "AI建议标签": _multi(response.ai_suggested_tags),
            "教师评分": _format_scores(response.teacher_dimension_scores or {}),
            "教师标签": _multi(response.teacher_tags),
            "教师批注": response.teacher_note or "",
            "状态": _single(status),
            "更新时间": _ms(datetime.utcnow()),
        }
    }


# ── Configuration & status (no secrets) ─────────────────────────────────

def bitable_is_configured(config: FeishuConfig) -> bool:
    table_ids = config.bitable_table_ids or {}
    return bool(config.bitable_app_token and table_ids.get("responses"))


def bitable_status(config: FeishuConfig) -> dict[str, Any]:
    table_ids = config.bitable_table_ids or {}
    return {
        "mode": "ready" if bitable_is_configured(config) else "deferred",
        "configured": bool(config.bitable_app_token),
        "app_token": (
            config.bitable_app_token[:8] + "..." if config.bitable_app_token else ""
        ),
        "table_ids": {k: bool(v) for k, v in table_ids.items()},
    }


# ── Sync service ────────────────────────────────────────────────────────

class BitableSyncer:
    def __init__(
        self,
        client: FeishuClient,
        config: Optional[FeishuConfig] = None,
    ) -> None:
        self.client = client
        self.config = config or client.config
        self.service = BitableService(client)

    @property
    def available(self) -> bool:
        return bitable_is_configured(self.config)

    def _table_id(self, key: str) -> str:
        return (self.config.bitable_table_ids or {}).get(key, "")

    async def _upsert(
        self,
        db: Session,
        table_key: str,
        entity_type: str,
        entity_id: int,
        record: dict,
    ) -> dict:
        table_id = self._table_id(table_key)
        if not table_id:
            return {"status": "skipped", "reason": f"table {table_key} not configured"}

        binding = (
            db.query(FeishuBinding)
            .filter(
                FeishuBinding.entity_type == entity_type,
                FeishuBinding.entity_id == entity_id,
                FeishuBinding.table_key == table_key,
            )
            .first()
        )
        try:
            if binding and binding.remote_record_id:
                await self.service.batch_update_records(
                    table_id,
                    [{"record_id": binding.remote_record_id, **record}],
                )
                return {"status": "updated"}

            data = await self.service.batch_create_records(table_id, [record])
            records = (data or {}).get("records") or []
            remote_id = str(records[0].get("record_id") or "") if records else ""
            if not remote_id:
                return {"status": "error", "reason": "batch_create returned no record_id"}
            if binding is None:
                binding = FeishuBinding(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    table_key=table_key,
                )
                db.add(binding)
            binding.remote_record_id = remote_id
            db.commit()
            return {"status": "created"}
        except Exception as exc:  # noqa: BLE001 - sync must never break the main flow
            db.rollback()
            return {"status": "error", "reason": str(exc)}

    async def _sync_one(
        self,
        db: Session,
        table_key: str,
        entity,
        record: dict,
        summary: dict,
    ) -> None:
        entity_type = ENTITY_TYPE_BY_TABLE[table_key]
        result = await self._upsert(
            db, table_key, entity_type, entity.id, record
        )
        counters = summary["tables"][table_key]
        status = result["status"]
        if status in counters:
            counters[status] += 1
        else:
            counters["errors"] += 1

    async def sync_course(self, db: Session, course_id: int) -> dict:
        if not self.available:
            return {"configured": False, "mode": "deferred", "tables": {}}
        summary = {
            "configured": True,
            "tables": {
                key: {"created": 0, "updated": 0, "errors": 0, "skipped": 0}
                for key in TABLE_KEYS
            },
        }
        course = db.get(Course, course_id)
        if not course:
            return {"configured": True, "error": "course not found"}

        await self._sync_one(db, "courses", course, build_course_record(course), summary)
        for topic in course.topics:
            await self._sync_one(db, "topics", topic, build_topic_record(topic), summary)
        for student in course.students:
            await self._sync_one(db, "students", student, build_student_record(student), summary)
        responses = (
            db.query(StudentResponse)
            .join(Student, StudentResponse.student_id == Student.id)
            .filter(Student.course_id == course_id)
            .all()
        )
        for resp in responses:
            await self._sync_one(
                db,
                "responses",
                resp,
                build_response_record(resp, resp.student, resp.topic),
                summary,
            )
        return summary

    async def sync_response(self, db: Session, response_id: int) -> dict:
        if not self.available:
            return {"configured": False, "mode": "deferred", "tables": {}}
        resp = db.get(StudentResponse, response_id)
        if not resp:
            return {"configured": True, "error": "response not found"}
        summary = {
            "configured": True,
            "tables": {
                "responses": {"created": 0, "updated": 0, "errors": 0, "skipped": 0}
            },
        }
        await self._sync_one(
            db,
            "responses",
            resp,
            build_response_record(resp, resp.student, resp.topic),
            summary,
        )
        return summary
