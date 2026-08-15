"""Assess all pending responses of a course with the real LLM pipeline, no uvicorn.

Usage:
    python assess_demo_data.py [--course 1] [--dry-run] [--force]

Standalone offline runner for the GitHub Pages demo snapshot: talks to SQLite
and the grading pipeline directly. Mirrors api/assessment.py::_run_assessment
semantics (skip rules, result write-back, AI-tag library sync) so the exported
snapshot is identical to what the real batch assessment endpoint produces.

    --dry-run   fill deterministic fake results without calling the LLM
                (pipeline smoke test; safe without an API key)
    --force     re-assess responses that already carry AI scores
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api import state  # noqa: E402
from database import (  # noqa: E402
    Course,
    DebateTopic,
    SessionLocal,
    Student,
    StudentResponse,
    init_db,
)
from feishu.reviews import sync_tags_to_library  # noqa: E402
from grading.rubric_loader import RubricLoader  # noqa: E402

# Dry-run needs visibly different score bands so the replay demo shows the AI
# can discriminate between students (the whole point of the exercise).
_DRY_RUN_TIERS = [
    {"position": "A+", "material": "A", "structure": "A", "language": "A-", "perspective": "A"},
    {"position": "A", "material": "A-", "structure": "B+", "language": "A-", "perspective": "B+"},
    {"position": "B+", "material": "B", "structure": "B", "language": "B+", "perspective": "B"},
]


def _dry_run_result(student: Student, topic: DebateTopic, raw_text: str) -> dict:
    scores = _DRY_RUN_TIERS[(student.id * 31 + topic.id * 7) % len(_DRY_RUN_TIERS)]
    return {
        "cleaned_text": raw_text,
        "dimension_scores": scores,
        "confidence": "certain_good",
        "reasoning": {
            dim: {"evidence": "（dry-run 模拟）", "reasoning": "dry-run 模拟评级", "rating": r}
            for dim, r in scores.items()
        },
        "extracted_features": {"arguments_count": 2, "dry_run": True},
        "bonus_flags": [],
        "note": "dry-run 模拟结果（未调用 LLM）",
        "suggested_tags": ["观点明确"],
    }


def _apply_result(resp: StudentResponse, result: dict, db, cid: int) -> None:
    """Write assessment result back to the response row (same fields as the API)."""
    resp.cleaned_text = result.get("cleaned_text", "")
    resp.ai_dimension_scores = result.get("dimension_scores")
    resp.ai_confidence = result.get("confidence", "uncertain")
    resp.ai_reasoning = result.get("reasoning", {})
    resp.ai_extracted_features = result.get("extracted_features", {})
    resp.ai_bonus_flags = result.get("bonus_flags", [])
    resp.ai_note = result.get("note", "")
    resp.ai_suggested_tags = result.get("suggested_tags", [])
    new_tags = result.get("suggested_tags", [])
    if new_tags:
        sync_tags_to_library(db, cid, new_tags, source="ai")


async def _assess_course(cid: int, force: bool, dry_run: bool) -> dict:
    db = SessionLocal()
    try:
        # Push DB-backed settings into env and rebuild llm/evaluator singletons,
        # so keys changed in the settings UI behave exactly like under uvicorn.
        state.reload_runtime_settings(db)
        loader = RubricLoader(db)

        topics = (
            db.query(DebateTopic)
            .filter(DebateTopic.course_id == cid)
            .order_by(DebateTopic.order)
            .all()
        )
        students = db.query(Student).filter(Student.course_id == cid).all()
        if not topics or not students:
            raise SystemExit("course has no topics or no students - run seed.py first")

        summary = {"assessed": 0, "skipped": 0, "errors": 0, "llm_calls": 0}
        total = sum(
            1
            for s in students
            for t in topics
            if db.query(StudentResponse)
            .filter(StudentResponse.student_id == s.id, StudentResponse.topic_id == t.id)
            .first()
        )
        done = 0
        for student in students:
            for topic in topics:
                resp = (
                    db.query(StudentResponse)
                    .filter(
                        StudentResponse.student_id == student.id,
                        StudentResponse.topic_id == topic.id,
                    )
                    .first()
                )
                if not resp:
                    continue  # no response record = student didn't answer
                done += 1
                label = f"[{done}/{total}] {student.name} × {topic.title[:18]}…"

                if resp.ai_dimension_scores is not None and resp.ai_confidence != "uncertain":
                    if not force:
                        summary["skipped"] += 1
                        print(f"{label} skip (already assessed, use --force to redo)")
                        continue
                # NOTE: unlike the batch API we do NOT skip teacher_reviewed
                # rows. Seed ships teacher-reviewed responses WITHOUT an AI
                # result; this script backfills the AI view so the snapshot
                # shows "AI score vs teacher correction" side by side.
                raw_text = resp.raw_text or ""
                if not raw_text.strip():
                    summary["skipped"] += 1
                    print(f"{label} skip (empty response)")
                    continue

                try:
                    if dry_run:
                        result = _dry_run_result(student, topic, raw_text)
                    else:
                        cal_records = loader.get_calibration_records(
                            teacher_id="default", limit=10
                        )
                        result = await state.evaluator.assess(
                            rubric_loader=loader,
                            cognitive_tier=student.cognitive_tier,
                            topic_title=topic.title,
                            topic_type=topic.topic_type,
                            stimulus_material=topic.stimulus_material or "",
                            reference_arguments=topic.reference_arguments or [],
                            raw_text=raw_text,
                            student_grade=student.grade,
                            calibration_records=cal_records if cal_records else None,
                        )
                    _apply_result(resp, result, db, cid)
                    db.commit()
                    summary["assessed"] += 1
                    if not dry_run:
                        summary["llm_calls"] += 2  # clean + evaluate
                    scores = resp.ai_dimension_scores or {}
                    pretty = "/".join(str(v) for v in scores.values()) if scores else "?"
                    print(f"{label} OK  {pretty}")
                except Exception as e:  # noqa: BLE001 - same error contract as the API
                    resp.cleaned_text = ""
                    resp.ai_dimension_scores = None
                    resp.ai_confidence = "uncertain"
                    resp.ai_reasoning = {}
                    resp.ai_extracted_features = {}
                    resp.ai_suggested_tags = []
                    resp.ai_note = f"AI评估异常：{e}"
                    db.commit()
                    summary["errors"] += 1
                    print(f"{label} ERROR  {e}")
        return summary
    finally:
        db.close()


def main() -> None:
    # Windows GBK consoles choke on CJK prints; force UTF-8 with replacement.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--course", type=int, default=None, help="course id (default: first)")
    parser.add_argument("--dry-run", action="store_true", help="fake results, no LLM calls")
    parser.add_argument("--force", action="store_true", help="re-assess existing AI scores")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        cid = args.course
        if cid is None:
            first = db.query(Course).order_by(Course.id).first()
            if not first:
                raise SystemExit("no course found - run seed.py first")
            cid = first.id
    finally:
        db.close()

    mode = "dry-run" if args.dry_run else "LLM"
    print(f"== assess_demo_data: course {cid} ({mode}) ==")
    summary = asyncio.run(_assess_course(cid, force=args.force, dry_run=args.dry_run))
    print(
        f"== done: assessed={summary['assessed']} skipped={summary['skipped']} "
        f"errors={summary['errors']} llm_calls={summary['llm_calls']} =="
    )
    if summary["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
