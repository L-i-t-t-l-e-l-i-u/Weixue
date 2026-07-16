"""Rubric loader: cognitive-tier-aware prompt assembly.

Loads RubricTemplate from database by cognitive_tier and builds
complete evaluation prompts with dimension definitions, weights,
negative indicators, and optional teacher calibration examples.
"""

from typing import Optional
from sqlalchemy.orm import Session
from .llm import LLMClient
from database import RubricTemplate, CalibrationRecord, StudentResponse, Student, get_cognitive_tier


class RubricLoader:
    """Loads and assembles cognitive-tier-specific evaluation prompts."""

    def __init__(self, db: Session):
        self.db = db
        self._cache: dict[str, RubricTemplate] = {}

    def get_template(self, cognitive_tier: str) -> Optional[RubricTemplate]:
        """Load RubricTemplate by cognitive_tier, with in-memory caching."""
        if cognitive_tier in self._cache:
            return self._cache[cognitive_tier]

        template = (
            self.db.query(RubricTemplate)
            .filter(RubricTemplate.cognitive_tier == cognitive_tier)
            .first()
        )
        if template:
            self._cache[cognitive_tier] = template
        return template

    def build_system_prompt(
        self,
        cognitive_tier: str,
        calibration_records: list[CalibrationRecord] | None = None,
    ) -> str:
        """Build the complete system prompt for a given cognitive tier.

        Args:
            cognitive_tier: basic / developing / advancing
            calibration_records: optional list of teacher calibration records
                to inject as few-shot examples

        Returns:
            Complete system prompt string for the LLM evaluator.
        """
        template = self.get_template(cognitive_tier)
        if not template:
            return self._fallback_prompt(cognitive_tier)

        prompt = template.prompt_template

        # Inject dimension definitions
        definitions_block = self._build_definitions_block(
            template.active_dimensions,
            template.rubric_definitions,
            template.dimension_weights,
        )
        prompt = prompt.replace("{DIMENSION_DEFINITIONS}", definitions_block)

        # Inject negative indicators
        negatives_block = self._build_negatives_block(template.negative_indicators)
        prompt = prompt.replace("{NEGATIVE_INDICATORS}", negatives_block)

        # Inject calibration examples if available
        if calibration_records:
            calibration_block = self._build_calibration_block(calibration_records)
            prompt = prompt.replace("{CALIBRATION_EXAMPLES}", calibration_block)
        else:
            prompt = prompt.replace("{CALIBRATION_EXAMPLES}", "")

        return prompt

    def build_user_prompt(
        self,
        topic_title: str,
        topic_type: str,
        stimulus_material: str,
        reference_arguments: list[str],
        student_text: str,
        student_grade: int,
    ) -> str:
        """Build the user prompt for a specific student response.

        Args:
            topic_title: the debate question
            topic_type: dilemma / fact_opinion / causal
            stimulus_material: any provided context material
            reference_arguments: list of reference pro/con arguments
            student_text: the student's response (cleaned or raw)
            student_grade: student's grade (1-7)

        Returns:
            User prompt string.
        """
        parts = [
            f"思辨主题：{topic_title}",
            f"议题类型：{self._topic_type_label(topic_type)}",
            f"学生年级：{student_grade}年级",
        ]

        if stimulus_material:
            parts.append(f"引导材料：\n{stimulus_material}")

        if reference_arguments:
            args_str = "\n".join(f"  - {a}" for a in reference_arguments)
            parts.append(f"参考论据库：\n{args_str}")

        parts.append(f"\n学生作答：\n{student_text}")
        parts.append("\n请按上述系统指令中的评估维度逐一分析该学生的作答。")

        return "\n\n".join(parts)

    def get_calibration_records(
        self,
        teacher_id: str = "default",
        cognitive_tier: str | None = None,
        limit: int = 5,
    ) -> list[CalibrationRecord]:
        """Retrieve recent teacher calibration records for few-shot injection.

        In a production system, this would use semantic similarity search.
        For the demo, we filter by cognitive_tier (via the student's grade)
        and return the most recent records.
        """
        query = (
            self.db.query(CalibrationRecord)
            .join(StudentResponse)
            .join(Student)
            .filter(CalibrationRecord.teacher_id == teacher_id)
        )

        if cognitive_tier:
            # Filter students whose grade maps to this cognitive_tier
            valid_grades = []
            for g in range(1, 8):
                if get_cognitive_tier(g) == cognitive_tier:
                    valid_grades.append(g)
            query = query.filter(Student.grade.in_(valid_grades))

        records = (
            query
            .order_by(CalibrationRecord.created_at.desc())
            .limit(limit)
            .all()
        )
        return records

    # ── Internal builders ───────────────────────────────────

    @staticmethod
    def _build_definitions_block(
        active_dimensions: list[str],
        rubric_definitions: dict,
        dimension_weights: dict,
    ) -> str:
        """Build the dimension definitions section of the prompt."""
        lines = ["你需要从以下维度评估学生的作答：\n"]

        for dim in active_dimensions:
            defn = rubric_definitions.get(dim, {})
            weight = dimension_weights.get(dim, 0)
            name = defn.get("name", dim)
            description = defn.get("description", "")
            weight_pct = f"{int(weight * 100)}%"

            lines.append(f"【{name}】（权重 {weight_pct}）")
            lines.append(f"  {description}")

            # Level definitions (A+/A/A-/B+/B/B-)
            levels = defn.get("levels", {})
            if levels:
                for level_key in ["A+", "A", "A-", "B+", "B", "B-"]:
                    if level_key in levels:
                        lines.append(f"  {level_key}级：{levels[level_key]}")

            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _build_negatives_block(negative_indicators: dict) -> str:
        """Build the negative indicators section."""
        if not negative_indicators:
            return ""

        lines = [
            "【反向指标 — 以下特征应导致对应维度降级】\n"
        ]
        for dim, indicator in negative_indicators.items():
            lines.append(f"- {dim}：{indicator}")

        return "\n".join(lines)

    @staticmethod
    def _build_calibration_block(records: list[CalibrationRecord]) -> str:
        """Build few-shot calibration examples from teacher records.

        Compact format: AI scores → teacher scores → reason (if any).
        """
        if not records:
            return ""

        dim_labels = {
            "clarity": "清晰性", "interpretation": "解释力",
            "evidence_awareness": "证据意识", "relevance": "相关性",
            "inference": "因果推理", "evidence_use": "证据使用",
            "argument_evaluation": "论证质量", "depth_breadth": "深度广度",
            "self_regulation": "反思调节",
        }

        def format_scores(scores: dict) -> str:
            if not scores:
                return "无"
            parts = []
            for dim, rating in scores.items():
                label = dim_labels.get(dim, dim)
                parts.append(f"{label}{rating}")
            return "、".join(parts)

        lines = [
            "【教师校准偏好参考 — 请参照以下历史修正记录调整你的评分倾向】\n"
        ]

        for i, rec in enumerate(records, 1):
            ai_scores = format_scores(rec.ai_original_scores or {})
            teacher_scores = format_scores(rec.teacher_final_scores or {})

            # Extract reasons from modifications
            reasons = []
            for m in (rec.modifications or []):
                if isinstance(m, dict):
                    reason = m.get("reason", "")
                    if reason:
                        reasons.append(reason)
            reason_str = "；".join(reasons) if reasons else (rec.note or "")

            lines.append(f"校准{i}  AI评分：{ai_scores}")
            lines.append(f"        教师修正：{teacher_scores}")
            if reason_str:
                lines.append(f"        教师理由：{reason_str}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _topic_type_label(topic_type: str) -> str:
        """Map topic_type enum to Chinese label."""
        labels = {
            "dilemma": "两难抉择类",
            "fact_opinion": "事实与观点区分类",
            "causal": "因果推导类",
        }
        return labels.get(topic_type, topic_type)

    @staticmethod
    def _fallback_prompt(cognitive_tier: str) -> str:
        """Fallback prompt when no RubricTemplate is found in database."""
        return (
            f"你是一位经验丰富的思辨课教师，正在评估学生的思辨能力表现。\n"
            f"当前学生的认知梯段为：{cognitive_tier}\n"
            f"请从清晰性、逻辑性、观点深度等维度对该学生的作答进行分析。\n"
            f"对每个维度给出 A+/A/A-/B+/B/B- 评级，并说明评级理由。\n"
            f"请按 JSON 格式返回结果。"
        )
