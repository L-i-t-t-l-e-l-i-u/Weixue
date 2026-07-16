"""FastAPI application — all routes for the critical thinking assessment system."""

import os
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
import threading

from database import (
    get_db, init_db, SessionLocal,
    Course, DebateTopic, Student, StudentResponse,
    RubricTemplate, CalibrationRecord, DimensionTag,
    get_cognitive_tier,
)
from schemas import (
    CourseCreate, CourseOut, DebateTopicCreate, DebateTopicOut,
    StudentCreate, StudentOut, StudentResponseOut, TeacherReview,
    CommentRequest, CommentOut, CommentSaveRequest, BatchCommentOut,
    TopicAnalytics, TagOut, TagUpdate, TagMerge,
    RubricTemplateOut, CalibrationRecordOut,
)
from grading.evaluator import AssessmentEngine
from grading.llm import LLMClient
from grading.rubric_loader import RubricLoader

app = FastAPI(title="思辨星 · 少儿思辨能力认知自适应评估系统", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

llm = LLMClient()
evaluator = AssessmentEngine(llm)

# Thread-safe assessment progress tracker
_assessment_progress = {}
_progress_lock = threading.Lock()


@app.on_event("startup")
def on_startup():
    init_db()


# ════════════════════════════════════════════════════════════
# Courses
# ════════════════════════════════════════════════════════════

@app.get("/api/courses", response_model=list[CourseOut])
def list_courses(db: Session = Depends(get_db)):
    courses = db.query(Course).all()
    result = []
    for c in courses:
        tc = db.query(DebateTopic).filter(DebateTopic.course_id == c.id).count()
        sc = db.query(Student).filter(Student.course_id == c.id).count()
        result.append(CourseOut(
            id=c.id, title=c.title, class_name=c.class_name,
            grade_level=c.grade_level, created_at=c.created_at,
            topic_count=tc, student_count=sc,
        ))
    return result


@app.get("/api/courses/{cid}", response_model=CourseOut)
def get_course(cid: int, db: Session = Depends(get_db)):
    c = db.query(Course).get(cid)
    if not c:
        raise HTTPException(404, "Course not found")
    tc = db.query(DebateTopic).filter(DebateTopic.course_id == cid).count()
    sc = db.query(Student).filter(Student.course_id == cid).count()
    return CourseOut(
        id=c.id, title=c.title, class_name=c.class_name,
        grade_level=c.grade_level, created_at=c.created_at,
        topic_count=tc, student_count=sc,
    )


# ════════════════════════════════════════════════════════════
# Debate Topics
# ════════════════════════════════════════════════════════════

@app.get("/api/courses/{cid}/topics", response_model=list[DebateTopicOut])
def list_topics(cid: int, db: Session = Depends(get_db)):
    topics = db.query(DebateTopic).filter(DebateTopic.course_id == cid).order_by(DebateTopic.order).all()
    return topics


@app.post("/api/courses/{cid}/topics", response_model=DebateTopicOut)
def create_topic(cid: int, body: DebateTopicCreate, db: Session = Depends(get_db)):
    if not db.query(Course).get(cid):
        raise HTTPException(404, "Course not found")
    max_order = db.query(func.max(DebateTopic.order)).filter(DebateTopic.course_id == cid).scalar() or 0
    t = DebateTopic(course_id=cid, order=max_order + 1, **body.model_dump())
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ════════════════════════════════════════════════════════════
# Students
# ════════════════════════════════════════════════════════════

@app.get("/api/courses/{cid}/students", response_model=list[StudentOut])
def list_students(cid: int, db: Session = Depends(get_db)):
    students = db.query(Student).filter(Student.course_id == cid).all()
    result = []
    for s in students:
        result.append(StudentOut(
            id=s.id, name=s.name, grade=s.grade,
            course_id=s.course_id, cognitive_tier=s.cognitive_tier,
            comment_draft=s.comment_draft or "",
        ))
    return result


@app.post("/api/courses/{cid}/students", response_model=StudentOut)
def create_student(cid: int, body: StudentCreate, db: Session = Depends(get_db)):
    if not db.query(Course).get(cid):
        raise HTTPException(404, "Course not found")
    s = Student(course_id=cid, name=body.name, grade=body.grade)
    db.add(s)
    db.commit()
    db.refresh(s)
    return StudentOut(
        id=s.id, name=s.name, grade=s.grade,
        course_id=s.course_id, cognitive_tier=s.cognitive_tier,
        comment_draft=s.comment_draft or "",
    )


# ════════════════════════════════════════════════════════════
# Student Responses & Assessment
# ════════════════════════════════════════════════════════════

@app.get("/api/courses/{cid}/responses", response_model=list[StudentResponseOut])
def list_responses(cid: int, student_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(StudentResponse).join(Student).filter(Student.course_id == cid)
    if student_id:
        q = q.filter(StudentResponse.student_id == student_id)
    return q.all()


@app.get("/api/responses/{rid}", response_model=StudentResponseOut)
def get_response(rid: int, db: Session = Depends(get_db)):
    resp = db.query(StudentResponse).get(rid)
    if not resp:
        raise HTTPException(404, "Response not found")
    return resp


@app.post("/api/courses/{cid}/assess")
async def assess_course(cid: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Kick off AI assessment for all student responses in a course."""
    course = db.query(Course).get(cid)
    if not course:
        raise HTTPException(404, "Course not found")

    with _progress_lock:
        if _assessment_progress.get(cid, {}).get("active"):
            raise HTTPException(409, "Assessment already in progress")

    topics = db.query(DebateTopic).filter(DebateTopic.course_id == cid).order_by(DebateTopic.order).all()
    students = db.query(Student).filter(Student.course_id == cid).all()

    if not topics or not students:
        raise HTTPException(400, "Need topics and students before assessment")

    # Count responses that need assessment (skip empty/unanswered)
    need_assessment = 0
    for student in students:
        for topic in topics:
            resp = db.query(StudentResponse).filter(
                StudentResponse.student_id == student.id,
                StudentResponse.topic_id == topic.id,
            ).first()
            if not resp:
                continue  # no response record = student didn't answer
            if not resp.raw_text or not resp.raw_text.strip():
                continue  # empty response = skip
            if resp.teacher_reviewed:
                continue
            if resp.ai_dimension_scores is not None and resp.ai_confidence != "uncertain":
                continue
            need_assessment += 1

    with _progress_lock:
        _assessment_progress[cid] = {
            "completed": 0, "total": need_assessment, "active": True,
            "errors": 0, "llm_calls": 0, "skipped": 0,
        }

    background_tasks.add_task(_run_assessment, cid, students, topics)
    return {"status": "started", "total": len(students) * len(topics), "need_assessment": need_assessment}


async def _run_assessment(cid: int, students, topics):
    """Background task: assess all student responses."""
    db = SessionLocal()
    loader = RubricLoader(db)

    try:
        for student in students:
            for topic in topics:
                resp = db.query(StudentResponse).filter(
                    StudentResponse.student_id == student.id,
                    StudentResponse.topic_id == topic.id,
                ).first()

                if not resp:
                    continue  # no response record = student didn't answer this topic, skip

                if resp.teacher_reviewed:
                    with _progress_lock:
                        _assessment_progress[cid]["completed"] += 1
                        _assessment_progress[cid]["skipped"] += 1
                    continue
                if resp.ai_dimension_scores is not None and resp.ai_confidence != "uncertain":
                    with _progress_lock:
                        _assessment_progress[cid]["completed"] += 1
                        _assessment_progress[cid]["skipped"] += 1
                    continue

                raw_text = resp.raw_text or ""
                if not raw_text.strip():
                    with _progress_lock:
                        _assessment_progress[cid]["completed"] += 1
                        _assessment_progress[cid]["skipped"] += 1
                    continue  # empty response, skip without sending to AI

                try:
                    # Get 10 most recent calibration records (no tier filter)
                    cal_records = loader.get_calibration_records(
                        teacher_id="default",
                        limit=10,
                    )

                    result = await evaluator.assess(
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

                    resp.cleaned_text = result.get("cleaned_text", "")
                    resp.ai_dimension_scores = result.get("dimension_scores")
                    resp.ai_confidence = result.get("confidence", "uncertain")
                    resp.ai_reasoning = result.get("reasoning", {})
                    resp.ai_extracted_features = result.get("extracted_features", {})
                    resp.ai_note = result.get("note", "")
                    resp.ai_suggested_tags = result.get("suggested_tags", [])

                    # Sync AI suggested tags to DimensionTag library
                    new_tags = result.get("suggested_tags", [])
                    if new_tags:
                        _sync_tags_to_library(db, cid, new_tags, source="ai")

                    db.commit()

                    with _progress_lock:
                        _assessment_progress[cid]["completed"] += 1
                        _assessment_progress[cid]["llm_calls"] += 1

                except Exception as e:
                    resp.ai_confidence = "uncertain"
                    resp.ai_note = f"AI评估异常：{e}"
                    db.commit()
                    with _progress_lock:
                        _assessment_progress[cid]["completed"] += 1
                        _assessment_progress[cid]["errors"] += 1
    finally:
        with _progress_lock:
            _assessment_progress[cid]["active"] = False
        db.close()


@app.get("/api/courses/{cid}/assessment-progress")
def assessment_progress(cid: int):
    """Poll assessment progress. Frontend calls this every 500ms."""
    with _progress_lock:
        p = _assessment_progress.get(cid, {
            "completed": 0, "total": 0, "active": False,
            "errors": 0, "llm_calls": 0, "skipped": 0,
        })
    return p


@app.post("/api/courses/{cid}/reset")
def reset_course(cid: int, db: Session = Depends(get_db)):
    """Reset all assessment data for this course."""
    responses = db.query(StudentResponse).join(Student).filter(
        Student.course_id == cid
    ).all()

    for resp in responses:
        resp.cleaned_text = ""
        resp.ai_dimension_scores = None
        resp.ai_confidence = "uncertain"
        resp.ai_reasoning = {}
        resp.ai_extracted_features = {}
        resp.ai_note = ""
        resp.ai_suggested_tags = []
        resp.teacher_dimension_scores = None
        resp.teacher_confidence_override = None
        resp.teacher_tags = []
        resp.teacher_note = ""
        resp.teacher_reviewed = False

    # Reset tags: remove AI-new and teacher-created tags, reset base use_count
    db.query(DimensionTag).filter(
        DimensionTag.course_id == cid,
        DimensionTag.source.in_(["ai_new", "teacher"]),
    ).delete(synchronize_session=False)
    db.query(DimensionTag).filter(DimensionTag.course_id == cid).update(
        {"use_count": 0}, synchronize_session=False
    )

    with _progress_lock:
        _assessment_progress.pop(cid, None)

    db.commit()
    return {"ok": True, "responses_reset": len(responses)}


def _sync_tags_to_library(db, course_id, tag_names, source="teacher"):
    """Ensure each tag name exists in DimensionTag and increment use_count."""
    for name in tag_names:
        if not name or not name.strip():
            continue
        tag = db.query(DimensionTag).filter(
            DimensionTag.course_id == course_id,
            DimensionTag.name == name,
        ).first()
        if tag:
            tag.use_count = (tag.use_count or 0) + 1
        else:
            tag = DimensionTag(
                course_id=course_id,
                name=name,
                source="ai_new" if source == "ai" else "teacher",
                use_count=1,
            )
            db.add(tag)


@app.post("/api/responses/{rid}/review", response_model=StudentResponseOut)
def review_response(rid: int, body: TeacherReview, db: Session = Depends(get_db)):
    """Teacher reviews/overrides AI assessment on specific dimensions."""
    resp = db.query(StudentResponse).get(rid)
    if not resp:
        raise HTTPException(404, "Response not found")

    # Save calibration record if teacher modified dimension scores
    if body.dimension_scores and resp.ai_dimension_scores:
        modifications = []
        for dim, new_rating in body.dimension_scores.items():
            old_rating = resp.ai_dimension_scores.get(dim)
            if old_rating and old_rating != new_rating:
                modifications.append({
                    "dimension": dim,
                    "from_rating": old_rating,
                    "to_rating": new_rating,
                    "reason": body.note or "",
                })

        if modifications:
            record = CalibrationRecord(
                response_id=rid,
                teacher_id="default",
                ai_original_scores=resp.ai_dimension_scores,
                teacher_final_scores=body.dimension_scores,
                modifications=modifications,
                note=body.note,
            )
            db.add(record)

    resp.teacher_dimension_scores = body.dimension_scores
    resp.teacher_confidence_override = body.confidence_override

    # Sync teacher-selected tags to DimensionTag library (diff-based)
    old_tags = set(resp.teacher_tags or [])
    new_tags = set(body.tags or [])
    course_id = resp.topic.course_id

    # Tags removed by teacher → decrement use_count
    for name in old_tags - new_tags:
        tag = db.query(DimensionTag).filter(
            DimensionTag.course_id == course_id,
            DimensionTag.name == name,
        ).first()
        if tag:
            tag.use_count = max((tag.use_count or 0) - 1, 0)

    resp.teacher_tags = body.tags
    resp.teacher_note = body.note
    resp.teacher_reviewed = True

    # Tags newly selected by teacher → find-or-create + increment use_count
    _sync_tags_to_library(db, course_id, list(new_tags - old_tags), source="teacher")

    db.commit()
    db.refresh(resp)
    return resp


# ════════════════════════════════════════════════════════════
# Comments
# ════════════════════════════════════════════════════════════

@app.post("/api/courses/{cid}/comments", response_model=CommentOut)
async def generate_comment(cid: int, body: CommentRequest, db: Session = Depends(get_db)):
    """Generate a personalized comment draft using LLM, incorporating teacher tags & notes."""
    student = db.query(Student).get(body.student_id)
    if not student or student.course_id != cid:
        raise HTTPException(404, "Student not found")

    topics = db.query(DebateTopic).filter(DebateTopic.course_id == cid).order_by(DebateTopic.order).all()
    responses = db.query(StudentResponse).filter(
        StudentResponse.student_id == body.student_id
    ).all()
    resp_map = {r.topic_id: r for r in responses}

    dim_labels = {
        "clarity": "清晰性", "interpretation": "解释力", "evidence_awareness": "证据意识",
        "relevance": "相关性", "inference": "因果推理", "evidence_use": "证据使用",
        "argument_evaluation": "论证质量", "depth_breadth": "深度广度", "self_regulation": "反思调节",
    }
    tier_labels = {"basic": "低年级（1-2年级）", "developing": "中年级（3-5年级）", "advancing": "高年级（6-7年级）"}

    # Collect per-topic teacher data
    topic_data = []
    reviewed_count = 0
    for topic in topics:
        r = resp_map.get(topic.id)
        if not r or not r.raw_text or not r.raw_text.strip():
            continue

        scores = r.teacher_dimension_scores or r.ai_dimension_scores
        is_reviewed = r.teacher_reviewed or False
        if is_reviewed:
            reviewed_count += 1

        score_parts = []
        if scores:
            for dim, rating in scores.items():
                label = dim_labels.get(dim, dim)
                score_parts.append(f"{label}: {rating}")

        tags = r.teacher_tags or r.ai_suggested_tags or []
        note = r.teacher_note or ""

        topic_data.append({
            "order": topic.order,
            "title": topic.title,
            "scores": "、".join(score_parts) if score_parts else "无评分",
            "tags": tags,
            "note": note,
            "reviewed": is_reviewed,
            "raw_text_preview": (r.raw_text[:80] + "...") if len(r.raw_text) > 80 else r.raw_text,
        })

    if reviewed_count == 0:
        return CommentOut(draft=f"提示：{student.name}同学尚无教师批改记录。请先在「评分」页面完成至少一个辩题的教师批改，再生成评语。")

    # Build LLM prompt
    topic_summaries = []
    for td in topic_data:
        lines = [f"辩题{td['order']}：{td['title']}"]
        lines.append(f"  评分：{td['scores']}")
        if td['tags']:
            lines.append(f"  教师选用标签：{'、'.join(td['tags'])}")
        if td['note']:
            lines.append(f"  教师批注：{td['note']}")
        if not td['reviewed']:
            lines.append("  （此题仅AI评分，教师未批改）")
        topic_summaries.append("\n".join(lines))

    prompt = (
        f"你是一位经验丰富的思辨课教师，正在为{student.name}同学（{tier_labels.get(student.cognitive_tier, '')}）撰写期末评语。\n\n"
        f"以下是{student.name}在各辩题中的表现数据和你的批改记录：\n\n"
        + "\n\n".join(topic_summaries)
        + "\n\n请撰写一段150-250字的个性化评语，要求：\n"
        "1. 用温暖但专业的语气，直接对学生说话（用'你'而非'该生'）\n"
        "2. 具体引用教师选用的标签和批注中的观察（这些是你的第一手判断，优先使用）\n"
        "3. 先肯定亮点（结合具体辩题表现），再指出1-2个提升方向\n"
        "4. 给出一个具体的下一步建议\n"
        "5. 不要用模板化的开头（如'在本次课程中'），直接进入个性化内容\n"
        "6. 不要列出所有维度的分数，而是用自然语言描述表现\n"
    )

    try:
        llm = LLMClient()
        draft = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=600,
        )
        draft = draft.strip()
    except Exception as e:
        # Fallback to template if LLM fails
        draft = _fallback_comment(student, topic_data, dim_labels)

    # Auto-save the draft
    student.comment_draft = draft
    db.commit()

    return CommentOut(draft=draft)


def _fallback_comment(student, topic_data, dim_labels):
    """Template fallback when LLM is unavailable."""
    name = student.name
    parts = [f"{name}同学在本次思辨课中表现积极。"]

    reviewed_topics = [t for t in topic_data if t['reviewed']]
    all_tags = []
    all_notes = []
    for t in reviewed_topics:
        all_tags.extend(t['tags'])
        if t['note']:
            all_notes.append(t['note'])

    if all_tags:
        unique_tags = list(dict.fromkeys(all_tags))[:4]
        parts.append(f"根据教师观察，你在「{'」「'.join(unique_tags)}」等方面有所体现。")

    if all_notes:
        parts.append(f"教师特别提到：{all_notes[0]}")

    parts.append("建议下一步继续加强论证中对具体证据的使用，并尝试从不同角度看问题。")

    return "\n\n".join(parts)


@app.post("/api/courses/{cid}/comments/save")
def save_comment_draft(cid: int, body: CommentSaveRequest, db: Session = Depends(get_db)):
    """Save a comment draft for a student."""
    student = db.query(Student).get(body.student_id)
    if not student or student.course_id != cid:
        raise HTTPException(404, "Student not found")
    student.comment_draft = body.draft
    db.commit()
    return {"ok": True, "student_id": body.student_id}


@app.post("/api/courses/{cid}/comments/batch", response_model=BatchCommentOut)
async def batch_generate_comments(cid: int, db: Session = Depends(get_db)):
    """Generate comments for all students who have at least one teacher-reviewed topic."""
    students = db.query(Student).filter(Student.course_id == cid).all()
    topics = db.query(DebateTopic).filter(DebateTopic.course_id == cid).order_by(DebateTopic.order).all()

    dim_labels = {
        "clarity": "清晰性", "interpretation": "解释力", "evidence_awareness": "证据意识",
        "relevance": "相关性", "inference": "因果推理", "evidence_use": "证据使用",
        "argument_evaluation": "论证质量", "depth_breadth": "深度广度", "self_regulation": "反思调节",
    }
    tier_labels = {"basic": "低年级（1-2年级）", "developing": "中年级（3-5年级）", "advancing": "高年级（6-7年级）"}

    results = []
    llm = LLMClient()

    for student in students:
        responses = db.query(StudentResponse).filter(
            StudentResponse.student_id == student.id
        ).all()
        resp_map = {r.topic_id: r for r in responses}

        # Check if any topic is teacher-reviewed
        reviewed_count = 0
        topic_summaries = []
        for topic in topics:
            r = resp_map.get(topic.id)
            if not r or not r.raw_text or not r.raw_text.strip():
                continue
            is_reviewed = r.teacher_reviewed or False
            if is_reviewed:
                reviewed_count += 1

            scores = r.teacher_dimension_scores or r.ai_dimension_scores
            score_parts = []
            if scores:
                for dim, rating in scores.items():
                    label = dim_labels.get(dim, dim)
                    score_parts.append(f"{label}: {rating}")
            tags = r.teacher_tags or r.ai_suggested_tags or []
            note = r.teacher_note or ""

            lines = [f"辩题{topic.order}：{topic.title}"]
            lines.append(f"  评分：{'、'.join(score_parts) if score_parts else '无评分'}")
            if tags:
                lines.append(f"  教师选用标签：{'、'.join(tags)}")
            if note:
                lines.append(f"  教师批注：{note}")
            if not is_reviewed:
                lines.append("  （此题仅AI评分，教师未批改）")
            topic_summaries.append("\n".join(lines))

        if reviewed_count == 0:
            results.append({
                "student_id": student.id,
                "student_name": student.name,
                "draft": "",
                "error": "无教师批改记录，跳过",
            })
            continue

        prompt = (
            f"你是一位经验丰富的思辨课教师，正在为{student.name}同学（{tier_labels.get(student.cognitive_tier, '')}）撰写期末评语。\n\n"
            f"以下是{student.name}在各辩题中的表现数据和你的批改记录：\n\n"
            + "\n\n".join(topic_summaries)
            + "\n\n请撰写一段150-250字的个性化评语，要求：\n"
            "1. 用温暖但专业的语气，直接对学生说话（用'你'而非'该生'）\n"
            "2. 具体引用教师选用的标签和批注中的观察（这些是你的第一手判断，优先使用）\n"
            "3. 先肯定亮点（结合具体辩题表现），再指出1-2个提升方向\n"
            "4. 给出一个具体的下一步建议\n"
            "5. 不要用模板化的开头（如'在本次课程中'），直接进入个性化内容\n"
            "6. 不要列出所有维度的分数，而是用自然语言描述表现\n"
        )

        try:
            draft = await llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=600,
            )
            draft = draft.strip()
            # Auto-save the draft
            student.comment_draft = draft
            db.commit()
            results.append({
                "student_id": student.id,
                "student_name": student.name,
                "draft": draft,
                "error": None,
            })
        except Exception as e:
            results.append({
                "student_id": student.id,
                "student_name": student.name,
                "draft": "",
                "error": str(e),
            })

    return BatchCommentOut(results=results)


# ════════════════════════════════════════════════════════════
# Teacher Calibration Records (for display)
# ════════════════════════════════════════════════════════════

@app.get("/api/courses/{cid}/calibrations")
def get_calibrations(cid: int, limit: int = 10, db: Session = Depends(get_db)):
    """Fetch recent teacher calibration records for display."""
    records = (
        db.query(CalibrationRecord)
        .join(StudentResponse)
        .join(Student)
        .filter(Student.course_id == cid)
        .order_by(CalibrationRecord.created_at.desc())
        .limit(limit)
        .all()
    )

    dim_labels = {
        "clarity": "清晰性", "interpretation": "解释力",
        "evidence_awareness": "证据意识", "relevance": "相关性",
        "inference": "因果推理", "evidence_use": "证据使用",
        "argument_evaluation": "论证质量", "depth_breadth": "深度广度",
        "self_regulation": "反思调节",
        # Chinese keys (for older records)
        "清晰性": "清晰性", "解释力": "解释力", "证据意识": "证据意识",
    }

    def format_scores(scores: dict) -> str:
        if not scores:
            return "无"
        parts = []
        for dim, rating in scores.items():
            label = dim_labels.get(dim, dim)
            parts.append(f"{label}{rating}")
        return "、".join(parts)

    result = []
    for rec in records:
        # Extract reasons from modifications
        reasons = []
        for m in (rec.modifications or []):
            if isinstance(m, dict):
                reason = m.get("reason", "")
                if reason:
                    reasons.append(reason)
        reason_str = "；".join(reasons) if reasons else rec.note

        result.append({
            "id": rec.id,
            "ai_scores": format_scores(rec.ai_original_scores or {}),
            "teacher_scores": format_scores(rec.teacher_final_scores or {}),
            "reason": reason_str or "",
            "created_at": rec.created_at.isoformat() if rec.created_at else "",
        })

    return {"total": len(records), "records": result}


# ════════════════════════════════════════════════════════════
# Lesson Prep Analytics
# ════════════════════════════════════════════════════════════

@app.get("/api/courses/{cid}/prep", response_model=list[TopicAnalytics])
def prep_analytics(cid: int, db: Session = Depends(get_db)):
    """Aggregate assessment results per topic for lesson prep."""
    topics = db.query(DebateTopic).filter(DebateTopic.course_id == cid).order_by(DebateTopic.order).all()
    students = db.query(Student).filter(Student.course_id == cid).all()

    rating_map = {"A": 4, "A+": 4, "B+": 3.5, "B": 3, "C+": 2.5, "C": 2, "D": 1}
    result = []

    for topic in topics:
        dim_scores = {}
        weak_students = []
        tag_counts = {}

        for st in students:
            resp = db.query(StudentResponse).filter(
                StudentResponse.student_id == st.id,
                StudentResponse.topic_id == topic.id,
            ).first()
            if not resp:
                continue

            scores = resp.teacher_dimension_scores or resp.ai_dimension_scores
            conf = resp.teacher_confidence_override or resp.ai_confidence
            if conf == "uncertain" and not resp.teacher_dimension_scores:
                continue

            if scores:
                student_avg = 0
                for dim, rating in scores.items():
                    val = rating_map.get(rating, 2)
                    if dim not in dim_scores:
                        dim_scores[dim] = []
                    dim_scores[dim].append(val)
                    student_avg += val
                student_avg /= len(scores) if scores else 1

                if student_avg < 2.5:
                    weak_students.append(f"{st.name}({student_avg:.1f})")

            tags = resp.teacher_tags or resp.ai_suggested_tags or []
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        avg_dim_scores = {}
        weak_dimensions = []
        for dim, vals in dim_scores.items():
            avg = sum(vals) / len(vals) if vals else 0
            avg_dim_scores[dim] = round(avg, 2)
            if avg < 2.5:
                weak_dimensions.append(dim)

        error_tags = [
            {"tag": t, "count": c}
            for t, c in sorted(tag_counts.items(), key=lambda x: -x[1])
        ]

        result.append(TopicAnalytics(
            topic_id=topic.id, title=topic.title, topic_type=topic.topic_type,
            cognitive_tier=topic.cognitive_tier,
            avg_dimension_scores=avg_dim_scores,
            weak_dimensions=weak_dimensions,
            low_students=weak_students,
            error_tags=error_tags,
        ))

    # Sort by weakest average dimension score
    result.sort(key=lambda x: min(x.avg_dimension_scores.values()) if x.avg_dimension_scores else 5)
    return result


# ════════════════════════════════════════════════════════════
# Tags
# ════════════════════════════════════════════════════════════

@app.get("/api/courses/{cid}/tags", response_model=list[TagOut])
def list_tags(cid: int, db: Session = Depends(get_db)):
    tags = db.query(DimensionTag).filter(DimensionTag.course_id == cid).order_by(DimensionTag.use_count.desc()).all()
    return tags


@app.post("/api/courses/{cid}/tags", response_model=TagOut)
def create_tag(cid: int, name: str, source: str = "base", db: Session = Depends(get_db)):
    existing = db.query(DimensionTag).filter(DimensionTag.course_id == cid, DimensionTag.name == name).first()
    if existing:
        return existing
    t = DimensionTag(course_id=cid, name=name, source=source)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@app.put("/api/tags/{tid}", response_model=TagOut)
def update_tag(tid: int, body: TagUpdate, db: Session = Depends(get_db)):
    tag = db.query(DimensionTag).get(tid)
    if not tag:
        raise HTTPException(404, "Tag not found")
    if body.name is not None:
        tag.name = body.name
    db.commit()
    db.refresh(tag)
    return tag


@app.post("/api/tags/merge", response_model=TagOut)
def merge_tags(body: TagMerge, db: Session = Depends(get_db)):
    keep = db.query(DimensionTag).get(body.keep_id)
    if not keep:
        raise HTTPException(404, "Keep tag not found")

    for mid in body.merge_ids:
        if mid == body.keep_id:
            continue
        merge_tag = db.query(DimensionTag).get(mid)
        if not merge_tag:
            continue
        keep.use_count += merge_tag.use_count
        tids = list(set((keep.topic_ids or []) + (merge_tag.topic_ids or [])))
        keep.topic_ids = tids
        # Update responses referencing the merged tag
        responses = db.query(StudentResponse).all()
        for resp in responses:
            if merge_tag.name in (resp.teacher_tags or []):
                resp.teacher_tags = [keep.name if t == merge_tag.name else t for t in resp.teacher_tags]
        db.delete(merge_tag)

    db.commit()
    db.refresh(keep)
    return keep


@app.delete("/api/tags/{tid}")
def delete_tag(tid: int, db: Session = Depends(get_db)):
    tag = db.query(DimensionTag).get(tid)
    if not tag:
        raise HTTPException(404, "Tag not found")
    db.delete(tag)
    db.commit()
    return {"ok": True}


# ════════════════════════════════════════════════════════════
# Report (class-level analytics)
# ════════════════════════════════════════════════════════════

@app.get("/api/courses/{cid}/report")
def class_report(cid: int, db: Session = Depends(get_db)):
    """Full class report: per-topic stats, per-student scores, top dimension tags."""
    topics = db.query(DebateTopic).filter(DebateTopic.course_id == cid).order_by(DebateTopic.order).all()
    students = db.query(Student).filter(Student.course_id == cid).all()

    rating_map = {"A": 4, "A+": 4, "B+": 3.5, "B": 3, "C+": 2.5, "C": 2, "D": 1}

    # Per-topic
    topic_stats = []
    for topic in topics:
        dim_scores = {}
        uncertain = 0
        for st in students:
            resp = db.query(StudentResponse).filter(
                StudentResponse.student_id == st.id,
                StudentResponse.topic_id == topic.id,
            ).first()
            if not resp:
                continue
            conf = resp.teacher_confidence_override or resp.ai_confidence
            scores = resp.teacher_dimension_scores or resp.ai_dimension_scores
            if conf == "uncertain" and not resp.teacher_dimension_scores:
                uncertain += 1
                continue
            if scores:
                for dim, rating in scores.items():
                    if dim not in dim_scores:
                        dim_scores[dim] = []
                    dim_scores[dim].append(rating_map.get(rating, 2))

        avg_dims = {d: round(sum(v) / len(v), 2) for d, v in dim_scores.items()} if dim_scores else {}
        topic_stats.append({
            "topic_id": topic.id, "title": topic.title,
            "cognitive_tier": topic.cognitive_tier,
            "avg_dimension_scores": avg_dims,
            "uncertain": uncertain,
        })

    # Per-student
    student_stats = []
    for st in students:
        all_vals = []
        unc = 0
        for topic in topics:
            resp = db.query(StudentResponse).filter(
                StudentResponse.student_id == st.id,
                StudentResponse.topic_id == topic.id,
            ).first()
            if not resp:
                continue
            conf = resp.teacher_confidence_override or resp.ai_confidence
            scores = resp.teacher_dimension_scores or resp.ai_dimension_scores
            if conf == "uncertain" and not resp.teacher_dimension_scores:
                unc += 1
            elif scores:
                for rating in scores.values():
                    all_vals.append(rating_map.get(rating, 2))

        avg_score = sum(all_vals) / len(all_vals) if all_vals else 0
        student_stats.append({
            "student_id": st.id, "name": st.name, "grade": st.grade,
            "cognitive_tier": st.cognitive_tier,
            "avg_score": round(avg_score, 2),
            "uncertain": unc,
        })

    # Top tags
    tags = db.query(DimensionTag).filter(DimensionTag.course_id == cid).order_by(
        DimensionTag.use_count.desc()
    ).limit(10).all()
    top_tags = [{"name": t.name, "count": t.use_count, "source": t.source} for t in tags]

    # Class average
    all_student_avgs = [s["avg_score"] for s in student_stats if s["avg_score"] > 0]
    class_avg = sum(all_student_avgs) / len(all_student_avgs) if all_student_avgs else 0

    return {
        "class_avg": round(class_avg, 2),
        "student_count": len(students),
        "topic_stats": topic_stats,
        "student_stats": student_stats,
        "top_tags": top_tags,
    }


# ════════════════════════════════════════════════════════════
# Rubric Templates (read-only)
# ════════════════════════════════════════════════════════════

@app.get("/api/rubric-templates", response_model=list[RubricTemplateOut])
def list_rubric_templates(db: Session = Depends(get_db)):
    return db.query(RubricTemplate).all()


# ════════════════════════════════════════════════════════════
# Calibration Records (read-only)
# ════════════════════════════════════════════════════════════

@app.get("/api/courses/{cid}/calibrations", response_model=list[CalibrationRecordOut])
def list_calibrations(cid: int, db: Session = Depends(get_db)):
    records = (
        db.query(CalibrationRecord)
        .join(StudentResponse)
        .join(Student)
        .filter(Student.course_id == cid)
        .order_by(CalibrationRecord.created_at.desc())
        .all()
    )
    return records


# ════════════════════════════════════════════════════════════
# Serve built frontend (production mode)
# ════════════════════════════════════════════════════════════

_frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist")

if os.path.isdir(_frontend_dir):
    @app.get("/")
    def _serve_index():
        return FileResponse(os.path.join(_frontend_dir, "index.html"))

    # Must come AFTER all other routes
    app.mount("/assets", StaticFiles(directory=os.path.join(_frontend_dir, "assets")), name="static-assets")

    @app.get("/{full_path:path}")
    def _spa_fallback(full_path: str):
        """SPA fallback: serve index.html for any non-API route."""
        return FileResponse(os.path.join(_frontend_dir, "index.html"))
