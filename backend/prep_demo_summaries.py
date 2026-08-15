"""Pre-generate real-LLM prep summaries (class + per-topic) into the demo snapshot DB.

Usage:
    python prep_demo_summaries.py [--course 1] [--dry-run]

Standalone offline runner for the GitHub Pages demo snapshot. Calls the SAME
digest builders, prompts and fallback templates as the api/prep.py summary
endpoints and persists the result on PrepPlan — export_demo_data.py then embeds
it, and the demo frontend replays the real AI text (badge "AI 生成") instead
of the deterministic template.

Run AFTER assess_demo_data.py (summaries describe assessment results) and
BEFORE export_demo_data.py.

    --dry-run   write the deterministic template instead of calling the LLM
                (smoke-test the export pipeline without an API key)
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api import state  # noqa: E402
from api.prep import (  # noqa: E402
    _build_summary_digest,
    _build_topic_summary_digest,
    _generate_prep_summary_llm,
    _generate_topic_summary_llm,
    _normalize_summary_field,
    _prep_insights,
    _prep_topic_rows,
    _template_prep_summary,
    _template_topic_summary,
)
from database import Course, PrepPlan, SessionLocal, init_db  # noqa: E402


def _normalize(summary: dict) -> dict:
    """Same three-field cleanup the endpoints apply before persisting."""
    return {
        **summary,
        "overview": _normalize_summary_field(summary.get("overview"), False),
        "problems": _normalize_summary_field(summary.get("problems"), True),
        "suggestions": _normalize_summary_field(summary.get("suggestions"), True),
    }


def _preview(text: str, n: int = 60) -> str:
    flat = " ".join(str(text or "").split())
    return flat[:n] + ("..." if len(flat) > n else "")


async def _generate(cid: int, dry_run: bool) -> dict:
    db = SessionLocal()
    try:
        # Same settings bootstrap as assess_demo_data.py so LLM keys behave
        # exactly like under uvicorn.
        state.reload_runtime_settings(db)
        course = db.get(Course, cid)
        if not course:
            raise SystemExit(f"course {cid} not found")

        insights = _prep_insights(cid, db)
        rows = _prep_topic_rows(cid, db)

        # 1) Class summary — same digest/prompt as POST /api/.../prep/summary.
        if dry_run:
            summary = _template_prep_summary(insights)
        else:
            summary = await _generate_prep_summary_llm(
                _build_summary_digest(course, insights)
            )
            if summary is None:
                print("WARNING: class LLM call failed - template fallback")
                try:
                    from grading.llm import LLMClient
                    probe = await LLMClient().chat_json(
                        messages=[{"role": "user", "content": 'Return JSON only: {"ok": true}'}],
                        temperature=0, max_tokens=50,
                    )
                    print(f"DEBUG probe reply: {probe!r}  (LLM reachable; failure was "
                          "likely a malformed/overlong summary response - just re-run)")
                except Exception as e:  # noqa: BLE001 - diagnostics only
                    print(f"DEBUG probe error: {type(e).__name__}: {e}")
                summary = _template_prep_summary(insights)
        summary = _normalize(summary)
        summary["generated_at"] = datetime.utcnow().isoformat()
        print(f"[class]   generated_by={summary.get('generated_by')}  {_preview(summary.get('overview'))}")

        # 2) Per-topic summaries — same as POST /api/.../prep/topics/{tid}/summary.
        topics_map = {}
        for row in rows:
            tid = row["topic_id"]
            hl = [h for h in insights["topic_highlights"] if h["topic_id"] == tid][:2]
            if dry_run:
                tsum = _template_topic_summary(row, hl)
            else:
                tsum = None
                digest = _build_topic_summary_digest(row, hl)
                for attempt in (1, 2, 3):
                    tsum = await _generate_topic_summary_llm(digest)
                    if tsum is not None:
                        break
                    print(f"WARNING: topic {tid} LLM attempt {attempt}/3 failed (digest {len(digest)} chars)")
                    await asyncio.sleep(2)
                if tsum is None:
                    # Differential probe: trivial call with the same client.
                    try:
                        from grading.llm import LLMClient
                        probe = await LLMClient().chat_json(
                            messages=[{"role": "user", "content": 'Return JSON only: {"ok": true}'}],
                            temperature=0, max_tokens=50,
                        )
                        print(f"DEBUG probe ok ({probe!r}) => LLM reachable; real topic "
                              f"prompt fails reproducibly - send me this line")
                    except Exception as e:  # noqa: BLE001
                        print(f"DEBUG probe error: {type(e).__name__}: {e}")
                if tsum is None:
                    tsum = _template_topic_summary(row, hl)
            tsum = _normalize(tsum)
            tsum["generated_at"] = datetime.utcnow().isoformat()
            topics_map[str(tid)] = tsum
            print(f"[topic {tid}] {row['title'][:20]}  generated_by={tsum.get('generated_by')}")

        # 3) Persist on PrepPlan exactly like the endpoints (single plan row).
        plan = db.query(PrepPlan).filter(PrepPlan.course_id == cid).first()
        if plan is None:
            plan = PrepPlan(course_id=cid)
            db.add(plan)
        plan.summary = {**summary, "topics": topics_map}
        plan.updated_at = datetime.utcnow()
        db.commit()

        all_llm = summary.get("generated_by") == "llm" and all(
            t.get("generated_by") == "llm" for t in topics_map.values()
        )
        return {"topics": len(topics_map), "all_llm": all_llm}
    finally:
        db.close()


def main() -> None:
    # Windows GBK consoles choke on CJK prints; force UTF-8 with replacement.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--course", type=int, default=None, help="course id (default: first)")
    parser.add_argument("--dry-run", action="store_true", help="template output, no LLM calls")
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
    print(f"== prep_demo_summaries: course {cid} ({mode}) ==")
    result = asyncio.run(_generate(cid, dry_run=args.dry_run))
    print(f"== done: class summary + {result['topics']} topic summaries, all_llm={result['all_llm']} ==")
    if not result["all_llm"] and not args.dry_run:
        print("Some summaries fell back to TEMPLATE - check the key/network and re-run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
