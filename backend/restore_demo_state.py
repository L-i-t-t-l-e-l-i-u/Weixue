"""Restore teacher review state into the local SQLite DB from a demo-data.json export.

Why this exists: UI operations such as the "重置" button clear teacher reviews
(teacher_dimension_scores / teacher_tags / teacher_reviewed) and remove teacher
and AI-new tags from the library, while keeping AI scores, calibration records
and comment drafts. If that happens, the comment-generation feature shows
"请先完成教师批改" and the demo no longer works end-to-end.

This script restores the course's demo state (all response fields + the full tag
library) from an exported demo-data.json snapshot (for example the one committed
in git), so the local SQLite DB matches the online GitHub Pages demo again.

Usage:
    python restore_demo_state.py --input <demo-data.json>
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (  # noqa: E402
    DimensionTag,
    SessionLocal,
    StudentResponse,
    init_db,
)


def _parse_json_field(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="path to demo-data.json snapshot")
    args = parser.parse_args()

    # utf-8-sig tolerates the BOM that some PowerShell exports prepend.
    with open(args.input, encoding="utf-8-sig") as fh:
        data = json.load(fh)

    init_db()
    db = SessionLocal()
    try:
        course_id = None
        if data.get("students"):
            course_id = data["students"][0].get("course_id")

        # 1) Overwrite responses with the canonical snapshot
        updated = 0
        for r in data.get("responses", []):
            resp = db.get(StudentResponse, r["id"])
            if not resp:
                continue
            resp.raw_text = r.get("raw_text") or ""
            resp.cleaned_text = r.get("cleaned_text") or ""
            resp.source = r.get("source") or "manual"
            resp.ai_dimension_scores = _parse_json_field(r.get("ai_dimension_scores"))
            resp.ai_confidence = r.get("ai_confidence") or "uncertain"
            resp.ai_reasoning = _parse_json_field(r.get("ai_reasoning")) or {}
            resp.ai_extracted_features = _parse_json_field(r.get("ai_extracted_features")) or {}
            resp.ai_note = r.get("ai_note") or ""
            resp.ai_suggested_tags = _parse_json_field(r.get("ai_suggested_tags")) or []
            resp.teacher_dimension_scores = _parse_json_field(r.get("teacher_dimension_scores"))
            resp.teacher_confidence_override = r.get("teacher_confidence_override")
            resp.teacher_tags = _parse_json_field(r.get("teacher_tags")) or []
            resp.teacher_note = r.get("teacher_note") or ""
            resp.teacher_reviewed = bool(r.get("teacher_reviewed"))
            updated += 1
        db.commit()

        # 2) Replace the course tag library with the snapshot (avoids duplicated
        #    near-identical AI tags from a re-run assessment).
        restored = 0
        if course_id is not None:
            db.query(DimensionTag).filter(DimensionTag.course_id == course_id).delete(
                synchronize_session=False
            )
            for t in data.get("tags", []):
                name = t.get("name", "")
                if not name:
                    continue
                db.add(
                    DimensionTag(
                        course_id=course_id,
                        name=name,
                        source=t.get("source", "base"),
                        use_count=t.get("use_count") or 0,
                        topic_ids=_parse_json_field(t.get("topic_ids")) or [],
                    )
                )
                restored += 1
        db.commit()

        total_tags = db.query(DimensionTag).filter(DimensionTag.course_id == course_id).count() if course_id else 0
        print(f"Restored {updated} responses, rebuilt tag library with {restored} tags")
        print(f"Tag library now has {total_tags} tags (course {course_id})")
        print("Run export_demo_data.py afterwards to refresh frontend/src/demo-data.json.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
