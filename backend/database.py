"""Database setup and SQLAlchemy ORM models.

Weixue critical thinking assessment system.
"""

import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean, Text,
    DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import sessionmaker, relationship, declarative_base

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "grading.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


# ── Cognitive tier helper ───────────────────────────────────

def get_cognitive_tier(grade: int) -> str:
    """Map grade (1-7) to cognitive tier based on Kuhn (1999) epistemological development.

    basic      (1-2年级): Absolutist — knowledge as direct copy of reality,
                           CT precursor skills (expression, simple causation)
    developing (3-5年级): Absolutist → Multiplist transition — can give reasons
                           but treats all opinions as equally valid
    advancing  (6-7年级): Multiplist → Evaluativist transition — can evaluate
                           argument quality and consider counter-arguments

    Reference: Kuhn, D. (1999). A Developmental Model of Critical Thinking.
    Educational Researcher, 28(2), 16-23.
    """
    if grade <= 2:
        return "basic"
    elif grade <= 5:
        return "developing"
    else:
        return "advancing"


# ── ORM Models ──────────────────────────────────────────────

class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    class_name = Column(String(100), nullable=False)
    grade_level = Column(Integer, nullable=False)   # primary target grade (1-7)
    created_at = Column(DateTime, default=datetime.utcnow)

    topics = relationship("DebateTopic", back_populates="course",
                          cascade="all, delete-orphan", order_by="DebateTopic.order")
    students = relationship("Student", back_populates="course",
                            cascade="all, delete-orphan")


class DebateTopic(Base):
    __tablename__ = "debate_topics"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    title = Column(String(300), nullable=False)          # the debate question
    topic_type = Column(String(50), default="dilemma")   # dilemma / fact_opinion / causal
    cognitive_tier = Column(String(20), default="developing")
    stimulus_material = Column(Text, default="")         # passage, image description, etc.
    reference_arguments = Column(JSON, default=list)     # ["pro argument 1", ...]
    rubric_template_id = Column(Integer, ForeignKey("rubric_templates.id"), nullable=True)
    max_score = Column(Integer, default=10)
    order = Column(Integer, default=0)

    course = relationship("Course", back_populates="topics")
    rubric_template = relationship("RubricTemplate")
    responses = relationship("StudentResponse", back_populates="topic",
                             cascade="all, delete-orphan")


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    name = Column(String(100), nullable=False)
    grade = Column(Integer, nullable=False)   # 1-7
    comment_draft = Column(Text, default="")  # saved comment draft

    course = relationship("Course", back_populates="students")
    responses = relationship("StudentResponse", back_populates="student",
                             cascade="all, delete-orphan")

    @property
    def cognitive_tier(self) -> str:
        return get_cognitive_tier(self.grade)


class StudentResponse(Base):
    __tablename__ = "student_responses"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    topic_id = Column(Integer, ForeignKey("debate_topics.id"), nullable=False)

    # Raw and cleaned text
    raw_text = Column(Text, default="")       # original speech/writing (with noise)
    cleaned_text = Column(Text, default="")   # after cleaning stage

    # AI multi-dimensional assessment
    ai_dimension_scores = Column(JSON, nullable=True)
    # e.g. {"clarity": "B", "relevance": "A", "inference": "C"}

    ai_confidence = Column(String(20), default="uncertain")
    # certain_good / certain_weak / uncertain

    ai_reasoning = Column(JSON, default=dict)
    # per-dimension reasoning chain:
    # {"clarity": {"evidence": "...", "reasoning": "...", "rating": "B"}, ...}

    ai_extracted_features = Column(JSON, default=dict)
    # {"arguments_count": 2, "counter_arguments": 0, "causal_connectors": ["因为","所以"], ...}

    ai_note = Column(Text, default="")
    ai_suggested_tags = Column(JSON, default=list)

    # Teacher override (per-dimension)
    teacher_dimension_scores = Column(JSON, nullable=True)
    teacher_confidence_override = Column(String(20), nullable=True)
    teacher_tags = Column(JSON, default=list)
    teacher_note = Column(Text, default="")
    teacher_reviewed = Column(Boolean, default=False)

    student = relationship("Student", back_populates="responses")
    topic = relationship("DebateTopic", back_populates="responses")
    calibrations = relationship("CalibrationRecord", back_populates="response",
                                cascade="all, delete-orphan")


class RubricTemplate(Base):
    """Cognitive-tier-specific rubric configuration.

    Each template defines which dimensions are active, their weights,
    behavioral anchor definitions, and negative indicators for the LLM.
    """
    __tablename__ = "rubric_templates"

    id = Column(Integer, primary_key=True, index=True)
    cognitive_tier = Column(String(20), nullable=False, unique=True)
    # basic / developing / advancing

    grade_range = Column(String(20), nullable=False)
    # e.g. "1-2", "3-5", "6-7"

    active_dimensions = Column(JSON, nullable=False)
    # ["clarity", "interpretation", "evidence_awareness"]

    dimension_weights = Column(JSON, nullable=False)
    # {"clarity": 0.4, "interpretation": 0.35, "evidence_awareness": 0.25}

    rubric_definitions = Column(JSON, nullable=False)
    # {"clarity": {"name": "清晰性", "description": "...", "levels": {"A": "...", "B": "...", ...}}, ...}

    negative_indicators = Column(JSON, nullable=False)
    # {"clarity": "无法理解学生在说什么，完全无法提取观点", ...}

    prompt_template = Column(Text, nullable=False)
    # LLM system prompt template for this tier

    created_at = Column(DateTime, default=datetime.utcnow)


class CalibrationRecord(Base):
    """Stores teacher corrections to AI assessments for feedback alignment.

    Each record captures one instance where the teacher modified AI-generated
    dimension scores. These records are retrieved as few-shot examples
    during subsequent assessments to align AI output with teacher preferences.
    """
    __tablename__ = "calibration_records"

    id = Column(Integer, primary_key=True, index=True)
    response_id = Column(Integer, ForeignKey("student_responses.id"), nullable=False)
    teacher_id = Column(String(50), default="default")

    ai_original_scores = Column(JSON, nullable=False)
    # {"clarity": "B", "relevance": "A", ...}

    teacher_final_scores = Column(JSON, nullable=False)
    # {"clarity": "B", "relevance": "A+", ...}

    modifications = Column(JSON, default=list)
    # [{"dimension": "relevance", "from": "B", "to": "A", "reason": "..."}, ...]

    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    response = relationship("StudentResponse", back_populates="calibrations")


class DimensionTag(Base):
    """Tags for categorizing critical thinking behaviors."""
    __tablename__ = "dimension_tags"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    name = Column(String(200), nullable=False)
    source = Column(String(20), default="base")   # base / ai_new
    use_count = Column(Integer, default=0)
    topic_ids = Column(JSON, default=list)


# ── Helpers ─────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
