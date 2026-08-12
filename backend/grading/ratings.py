"""Canonical six-level rating scale shared by backend analytics."""

RATING_VALUES = {
    "A+": 4.0,
    "A": 3.5,
    "A-": 3.0,
    "B+": 2.5,
    "B": 2.0,
    "B-": 1.0,
}

RATING_OPTIONS = tuple(RATING_VALUES)

# ── 合格线（教师口径，2026-08 确认）────────────────────────
# 六级评分 0-4 分制下按年级划分：
#   1-3 年级：≥ 2.5（B+）——“敢说、说清楚、能给出简单理由”
#   4-6 年级：≥ 3.0（A-）——“观点明确、有依据、能换角度”（7 年级并入此档）
# 判断按学生自己的年级，混龄班各按各的线。
PASS_LINE_LOWER_GRADES = (1, 2, 3)
PASS_LINE_LOWER = 2.5
PASS_LINE_UPPER = 3.0


def pass_line_for_grade(grade) -> float:
    """Return the passing score line for a student's grade band."""
    return PASS_LINE_LOWER if int(grade or 0) in PASS_LINE_LOWER_GRADES else PASS_LINE_UPPER


def is_passing(grade, value) -> bool:
    """True when a numeric score meets the student's grade-band pass line."""
    if value is None:
        return False
    return float(value) >= pass_line_for_grade(grade)


def rating_to_value(rating: str):
    """Return a numeric value, or None for an invalid/legacy rating."""
    return RATING_VALUES.get(rating)


# 维度 key 归一化：无论 LLM 返回中文维度名还是旧版英文 key，都统一为五维度标准 key。
DIMENSION_KEY_ALIASES = {
    # 中文标签（LLM 常直接把维度名当 key 返回）
    "立意（观点鲜明）": "position", "立意": "position",
    "选材（言之有物）": "material", "选材": "material",
    "结构（条理清晰）": "structure", "结构": "structure",
    "语言（用词准确）": "language", "语言": "language",
    "视角（换位思考）": "perspective", "视角": "perspective",
    # 旧版英文 key
    "clarity": "position", "interpretation": "position",
    "evidence_awareness": "material", "evidence_use": "material",
    "relevance": "structure", "inference": "structure",
    "argument_evaluation": "structure",
    "depth_breadth": "perspective", "self_regulation": "perspective",
}


def normalize_dimension_scores(scores):
    """Map any legacy/Chinese dimension keys to the canonical five-dimension keys."""
    if not isinstance(scores, dict):
        return scores
    out = {}
    for key, value in scores.items():
        out[DIMENSION_KEY_ALIASES.get(key, key)] = value
    return out
