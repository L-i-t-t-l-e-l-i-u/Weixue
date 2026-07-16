"""Pydantic schemas for API request/response validation."""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ── Course (was Assignment) ─────────────────────────────────

class CourseBase(BaseModel):
    title: str
    class_name: str
    grade_level: int

class CourseCreate(CourseBase):
    pass

class CourseOut(CourseBase):
    id: int
    created_at: datetime
    topic_count: int = 0
    student_count: int = 0
    class Config:
        from_attributes = True


# ── DebateTopic (was Question) ──────────────────────────────

class DebateTopicBase(BaseModel):
    title: str
    topic_type: str = "dilemma"
    cognitive_tier: str = "developing"
    stimulus_material: str = ""
    reference_arguments: list[str] = Field(default_factory=list)
    max_score: int = 10

class DebateTopicCreate(DebateTopicBase):
    rubric_template_id: Optional[int] = None

class DebateTopicOut(DebateTopicBase):
    id: int
    course_id: int
    rubric_template_id: Optional[int] = None
    order: int
    class Config:
        from_attributes = True


# ── Student ─────────────────────────────────────────────────

class StudentBase(BaseModel):
    name: str
    grade: int

class StudentCreate(StudentBase):
    pass

class StudentOut(StudentBase):
    id: int
    course_id: int
    cognitive_tier: str = ""
    comment_draft: str = ""
    class Config:
        from_attributes = True


# ── StudentResponse (was Submission) ────────────────────────

class DimensionScore(BaseModel):
    """Single dimension evaluation result."""
    dimension: str          # e.g. "clarity", "relevance"
    rating: str             # A+/A/A-/B+/B/B-
    evidence: str = ""      # text evidence from student response
    reasoning: str = ""     # why this rating was given

class AssessmentResult(BaseModel):
    """Full AI assessment result for one response."""
    dimension_scores: dict[str, str] = Field(default_factory=dict)
    # {"clarity": "B", "relevance": "A", ...}
    confidence: str = "uncertain"
    reasoning: dict = Field(default_factory=dict)
    extracted_features: dict = Field(default_factory=dict)
    note: str = ""
    suggested_tags: list[str] = Field(default_factory=list)

class StudentResponseOut(BaseModel):
    id: int
    student_id: int
    topic_id: int

    raw_text: str = ""
    cleaned_text: str = ""

    ai_dimension_scores: Optional[dict] = None
    ai_confidence: str = "uncertain"
    ai_reasoning: dict = Field(default_factory=dict)
    ai_extracted_features: dict = Field(default_factory=dict)
    ai_note: str = ""
    ai_suggested_tags: list = Field(default_factory=list)

    teacher_dimension_scores: Optional[dict] = None
    teacher_confidence_override: Optional[str] = None
    teacher_tags: list = Field(default_factory=list)
    teacher_note: str = ""
    teacher_reviewed: bool = False

    class Config:
        from_attributes = True

class TeacherReview(BaseModel):
    """Teacher overrides AI assessment on specific dimensions."""
    dimension_scores: Optional[dict[str, str]] = None
    confidence_override: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    note: str = ""


# ── RubricTemplate ──────────────────────────────────────────

class RubricTemplateOut(BaseModel):
    id: int
    cognitive_tier: str
    grade_range: str
    active_dimensions: list[str]
    dimension_weights: dict[str, float]
    rubric_definitions: dict
    negative_indicators: dict
    prompt_template: str
    class Config:
        from_attributes = True


# ── CalibrationRecord ───────────────────────────────────────

class CalibrationModification(BaseModel):
    dimension: str
    from_rating: str
    to_rating: str
    reason: str = ""

class CalibrationRecordOut(BaseModel):
    id: int
    response_id: int
    teacher_id: str = "default"
    ai_original_scores: dict
    teacher_final_scores: dict
    modifications: list[CalibrationModification] = Field(default_factory=list)
    note: str = ""
    created_at: datetime
    class Config:
        from_attributes = True

class CalibrationRecordCreate(BaseModel):
    response_id: int
    teacher_id: str = "default"
    ai_original_scores: dict
    teacher_final_scores: dict
    modifications: list[CalibrationModification] = Field(default_factory=list)
    note: str = ""


# ── Comment ─────────────────────────────────────────────────

class CommentRequest(BaseModel):
    student_id: int

class CommentOut(BaseModel):
    draft: str

class CommentSaveRequest(BaseModel):
    student_id: int
    draft: str

class BatchCommentOut(BaseModel):
    results: list[dict] = Field(default_factory=list)
    # [{"student_id": 1, "student_name": "小雨", "draft": "...", "error": null}, ...]


# ── Analytics ───────────────────────────────────────────────

class TopicAnalytics(BaseModel):
    topic_id: int
    title: str
    topic_type: str
    cognitive_tier: str
    avg_dimension_scores: dict[str, float] = Field(default_factory=dict)
    # {"clarity": 0.75, "relevance": 0.62, ...}
    weak_dimensions: list[str] = Field(default_factory=list)
    low_students: list[str] = Field(default_factory=list)
    error_tags: list[dict] = Field(default_factory=list)


# ── DimensionTag ────────────────────────────────────────────

class TagOut(BaseModel):
    id: int
    name: str
    source: str
    use_count: int
    topic_ids: list = Field(default_factory=list)
    class Config:
        from_attributes = True

class TagUpdate(BaseModel):
    name: Optional[str] = None

class TagMerge(BaseModel):
    keep_id: int
    merge_ids: list[int]
