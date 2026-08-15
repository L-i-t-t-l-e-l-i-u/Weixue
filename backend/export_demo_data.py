"""Export SQLite demo data to frontend/src/demo-data.json for GitHub Pages demo mode.

Usage:
    python export_demo_data.py [--course 1] [--output ../frontend/src/demo-data.json]

The frontend (src/api/demoClient.js) expects JSON columns to be serialized as
JSON strings (it re-parses them), so this script re-serializes them on export.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (  # noqa: E402
    CalibrationRecord,
    Course,
    DebateTopic,
    DimensionTag,
    PrepPlan,
    SessionLocal,
    Student,
    StudentResponse,
    init_db,
)

JSON_FIELDS = {
    "topics": ["reference_arguments"],
    "responses": [
        "ai_dimension_scores",
        "ai_reasoning",
        "ai_extracted_features",
        "ai_suggested_tags",
        "teacher_dimension_scores",
        "teacher_tags",
    ],
    "tags": ["topic_ids"],
    "calibrations": ["ai_original_scores", "teacher_final_scores", "modifications"],
    "prep_plans": ["lesson_plan", "notes", "summary"],
}


def row_dict(obj, kind: str) -> dict:
    d = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    for field in JSON_FIELDS.get(kind, []):
        if d.get(field) is not None:
            d[field] = json.dumps(d[field], ensure_ascii=False)
    for key, value in list(d.items()):
        if value is not None and hasattr(value, "isoformat"):
            d[key] = value.isoformat()
    return d


def dump_course(cid: int) -> dict:
    db = SessionLocal()
    try:
        course = db.get(Course, cid)
        if not course:
            raise SystemExit(f"course {cid} not found")
        topics = (
            db.query(DebateTopic)
            .filter(DebateTopic.course_id == cid)
            .order_by(DebateTopic.order)
            .all()
        )
        students = db.query(Student).filter(Student.course_id == cid).all()
        student_ids = [s.id for s in students]
        responses = (
            db.query(StudentResponse)
            .filter(StudentResponse.student_id.in_(student_ids))
            .order_by(StudentResponse.id)
            .all()
        )
        tags = (
            db.query(DimensionTag)
            .filter(DimensionTag.course_id == cid)
            .order_by(DimensionTag.id)
            .all()
        )
        response_ids = [r.id for r in responses]
        calibrations = (
            db.query(CalibrationRecord)
            .filter(CalibrationRecord.response_id.in_(response_ids))
            .order_by(CalibrationRecord.created_at.desc())
            .all()
        )
        prep_plans = (
            db.query(PrepPlan).filter(PrepPlan.course_id == cid).all()
        )
        return {
            "courses": [row_dict(course, "courses")],
            "topics": [row_dict(t, "topics") for t in topics],
            "students": [row_dict(s, "students") for s in students],
            "responses": [row_dict(r, "responses") for r in responses],
            "tags": [row_dict(t, "tags") for t in tags],
            "calibrations": [row_dict(c, "calibrations") for c in calibrations],
            "prep_plans": [row_dict(p, "prep_plans") for p in prep_plans],
        }
    finally:
        db.close()


def apply_replay_pending(data: dict, pending_ids: set, warn_missing_result: bool = True) -> dict:
    """Reset picked responses to not_started while keeping their AI results.

    The demo snapshot then ships a state gradient: some responses already
    assessed/reviewed (grading & prep pages have data on first paint) and some
    pending, so the batch-assess button in demo mode has something to replay.
    Teacher fields and calibrations of the picked rows are dropped — a pending
    response must look untouched.
    """
    if not pending_ids:
        return data
    cleared = 0
    missing_ai = []
    for r in data["responses"]:
        if r["id"] not in pending_ids:
            continue
        if not r.get("ai_dimension_scores"):
            missing_ai.append(r["id"])
        r["processing_status"] = "not_started"
        for field in (
            "teacher_dimension_scores",
            "teacher_tags",
            "teacher_note",
            "teacher_rating",
            "teacher_confidence_override",
        ):
            r[field] = None
        r["teacher_reviewed"] = False
        cleared += 1
    cal_before = len(data["calibrations"])
    data["calibrations"] = [
        c for c in data["calibrations"] if c["response_id"] not in pending_ids
    ]
    # Normalize: seed and assess_demo_data.py never write processing_status
    # (only the UI review endpoint does), so assessed rows can still read
    # not_started. Flip them to processed — every frontend consumer (incl.
    # StudentWindow, which has no teacher_reviewed fallback) then agrees.
    normalized = 0
    for r in data["responses"]:
        if r["id"] in pending_ids:
            continue
        if r.get("processing_status") in (None, "", "not_started") and (
            r.get("teacher_reviewed") or r.get("ai_dimension_scores")
        ):
            r["processing_status"] = "processed"
            normalized += 1
    print(
        f"replay-pending: {cleared} responses reset to not_started "
        f"(AI results kept), {cal_before - len(data['calibrations'])} calibrations dropped, "
        f"{normalized} assessed rows normalized to processed"
    )
    if missing_ai and warn_missing_result:
        print(
            f"WARNING: responses {missing_ai} have no AI result yet — replay "
            f"would fall back to mock scores. Run assess_demo_data.py first."
        )
    if cleared != len(pending_ids):
        print(f"WARNING: only {cleared} of {len(pending_ids)} requested ids matched this course")
    return data


def main() -> None:
    # Windows GBK consoles choke on CJK prints; force UTF-8 with replacement.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    default_out = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "frontend",
        "src",
        "demo-data.json",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course", type=int, default=None, help="course id (default: first)")
    parser.add_argument("--output", default=default_out, help="output json path")
    parser.add_argument(
        "--replay-pending",
        type=int,
        default=0,
        help="reset the newest N responses to not_started (AI results kept) so the "
        "demo batch-assess button can replay them",
    )
    parser.add_argument(
        "--pending-ids",
        default="",
        help="comma-separated response ids to reset instead of the newest N "
        "(overrides --replay-pending)",
    )
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

    data = dump_course(cid)

    if args.pending_ids:
        pending_ids = {int(x) for x in args.pending_ids.split(",") if x.strip()}
    elif args.replay_pending > 0:
        pending_ids = {r["id"] for r in data["responses"][-args.replay_pending:]}
    else:
        pending_ids = set()
    data = apply_replay_pending(data, pending_ids)

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    statuses = {}
    for r in data["responses"]:
        statuses[r["processing_status"]] = statuses.get(r["processing_status"], 0) + 1
    print(
        f"Exported course {cid} -> {os.path.abspath(args.output)} "
        f"({os.path.getsize(args.output)} bytes, statuses={statuses})"
    )


if __name__ == "__main__":
    main()
