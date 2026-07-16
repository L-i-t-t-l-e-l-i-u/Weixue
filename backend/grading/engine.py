"""Step-level math grading engine. Uses rule-based check + LLM for process analysis."""

import re
from typing import Optional
from .llm import LLMClient

SYSTEM_PROMPT = """\
你是一位经验丰富的高中数学教师，正在批改学生的数学作业。

你的任务是逐步分析学生的解题过程，对每一步给出判定：
- correct: 该步骤正确
- wrong: 该步骤有误（需在 note 中说明具体错因）
- derived_correct: 逻辑推导正确，但基于前面的错误前提

同时给出：
- confidence: certain_correct（确信整体正确）、certain_wrong（确信有明显错误）、uncertain（字迹/表述模糊，需教师核实）
- score_ratio: 0.0~1.0，过程分比例
- note: 给教师的简短说明
- suggested_tags: 2~4个错因标签（中文），用于后续学情分析

请严格按 JSON 格式返回，不要包含其他内容。

**重要规则（必须遵守）：**
- 必须将学生解答拆分为多个独立步骤，每步对应一个操作或推导
- 对于包含多个小问的复杂题目，steps 数组中至少包含 5 个步骤
- 严禁将学生整段答案作为一个步骤返回（此行为会被系统拒绝）
- 每个 step 的 text 应是一到两行推导，而非整段复制
{
  "steps": [
    {"text": "步骤内容", "correct": true/false, "note": "说明", "confidence": "certain/uncertain"}
  ],
  "overall": {
    "confidence": "certain_correct/certain_wrong/uncertain",
    "score_ratio": 0.0~1.0,
    "note": "给教师的评语",
    "suggested_tags": ["标签1", "标签2"]
  }
}
"""


class GradingEngine:
    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient()

    # ── Public API ──────────────────────────────────────────

    async def grade(
        self,
        question_title: str,
        standard_answer: str,
        solution_steps: list[str],
        student_text: str,
        max_score: int,
    ) -> dict:
        """Grade a single question submission. Returns GradingResult-shaped dict."""

        # Fast path: exact answer match → full score, no LLM call
        if self._exact_match(student_text, standard_answer):
            return {
                "score": float(max_score),
                "confidence": "certain_correct",
                "steps": [{"text": student_text.strip(), "correct": True,
                           "note": "", "confidence": "certain"}],
                "note": "",
                "suggested_tags": [],
                "_exact_match": True,
            }

        # LLM-based step analysis (with retry on blob)
        user_msg = self._build_user_prompt(
            question_title, standard_answer, solution_steps, student_text, max_score
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        try:
            result = await self.llm.chat_json(
                messages=messages, temperature=0.2, max_tokens=4000,
            )

            # ── Retry once if blob detected ──
            if self._is_blob(result):
                retry_msg = (
                    "你上一次返回的步骤太少或每步太长，系统已拒绝。\n"
                    "请重新分析，务必将学生解答拆分为 8 个以上的细粒度步骤，"
                    "每步只包含一到两行数学推导。"
                )
                messages.append({"role": "assistant", "content": "我需要重新分析。"})
                messages.append({"role": "user", "content": retry_msg})
                result = await self.llm.chat_json(
                    messages=messages, temperature=0.1, max_tokens=4000,
                )

            r = self._normalize(result, max_score)
            r["_exact_match"] = False
            return r
        except Exception as e:
            return {
                "score": None,
                "confidence": "uncertain",
                "steps": [],
                "note": f"AI批改失败（{e}），请教师手动审阅。",
                "suggested_tags": [],
                "_exact_match": False,
            }

    # ── Internals ───────────────────────────────────────────

    def _exact_match(self, student_text: str, standard_answer: str) -> bool:
        s = self._extract_final_value(student_text)
        a = self._extract_final_value(standard_answer)
        if not s or not a:
            return False
        return self._normalize_expr(s) == self._normalize_expr(a)

    @staticmethod
    def _extract_final_value(text: str) -> Optional[str]:
        """Extract the final numeric value from student/standard answer text.
        Handles: x=5, v=60km/h, x≈83.3元, x=12/7, x=125元, 125, etc.
        """
        # Try var=value patterns (x=, v=, etc.)
        m = re.findall(r'[a-zA-Z]\s*[=≈]\s*(-?\d[\d./]*)', text)
        if m:
            return m[-1].strip()
        # Try trailing number with optional unit
        m = re.findall(r'(-?\d[\d./]*)\s*(?:元|km/h|km|m|kg|度|分|秒|个|人|%)', text)
        if m:
            return m[-1].strip()
        # Fallback: last number-like token
        m = re.findall(r'(-?\d[\d./]*)', text)
        if m:
            return m[-1].strip()
        return None

    @staticmethod
    def _normalize_expr(expr: str) -> str:
        """Normalize a math expression for comparison."""
        expr = expr.replace(" ", "").replace(" ", "").lower()
        expr = expr.replace("（", "(").replace("）", ")")
        expr = expr.replace("＋", "+").replace("－", "-").replace("×", "*").replace("÷", "/")
        expr = expr.replace("≈", "=")
        # Try to evaluate simple fractions: 12/7 → keep as fraction string
        # For decimal comparison, evaluate if both are simple numbers
        try:
            if "/" in expr:
                num, den = expr.split("/")
                return str(round(float(num) / float(den), 6))
            return str(round(float(expr), 6))
        except (ValueError, ZeroDivisionError):
            return expr

    @staticmethod
    def _build_user_prompt(
        title: str, answer: str, steps: list[str], student: str, score: int
    ) -> str:
        steps_str = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))
        return (
            f"题目：{title}\n"
            f"满分：{score}分\n"
            f"标准答案：{answer}\n"
            f"标准解题步骤：\n{steps_str}\n\n"
            f"学生作答（OCR识别结果）：\n{student}\n\n"
            f"请逐步分析学生的解题过程。"
        )

    @staticmethod
    def _is_blob(raw: dict) -> bool:
        """Detect if LLM returned a lazy blob instead of granular steps."""
        steps = raw.get("steps", [])
        if len(steps) < 5:
            return True
        lengths = [len(s.get("text", "")) for s in steps]
        if any(l > 200 for l in lengths):
            return True
        if lengths and sum(lengths) / len(lengths) > 150:
            return True
        return False

    @staticmethod
    def _normalize(raw: dict, max_score: int) -> dict:
        """Normalize LLM response into GradingResult shape.

        Two-layer defense against score inflation:
        1. Validate step granularity (reject blob responses)
        2. Aggregate score from per-step correctness (not just overall.score_ratio)
        """
        overall = raw.get("overall", {})
        steps_raw = raw.get("steps", [])

        # ── Validate step granularity ──
        if GradingEngine._is_blob(raw):
            return {
                "score": None,
                "confidence": "uncertain",
                "steps": steps_raw,
                "note": ("AI 未能逐步分析，请教师审阅。"
                         + (overall.get("note", "") and " LLM备注: " + overall.get("note", ""))),
                "suggested_tags": overall.get("suggested_tags", []),
            }

        # ── Normalize step data ──
        steps = []
        for s in steps_raw:
            steps.append({
                "text": s.get("text", ""),
                "correct": s.get("correct", False),
                "note": s.get("note", ""),
                "confidence": s.get("confidence", "certain"),
            })

        # ── Aggregate score from per-step correctness ──
        correct_count = 0
        wrong_count = 0
        derived_count = 0
        first_wrong_idx = -1

        for i, s in enumerate(steps):
            c = s["correct"]
            # Handle both string labels and booleans
            if isinstance(c, str):
                if c == "derived_correct":
                    derived_count += 1
                    continue
                elif c == "correct":
                    correct_count += 1
                    continue
                else:  # "wrong" or other
                    wrong_count += 1
            elif c:  # boolean True
                correct_count += 1
                continue
            else:  # boolean False
                wrong_count += 1

            if first_wrong_idx == -1:
                first_wrong_idx = i

        # After first error, remaining correct steps → derived_correct
        if first_wrong_idx >= 0:
            for i in range(first_wrong_idx + 1, len(steps)):
                c = steps[i]["correct"]
                is_correct = (
                    (isinstance(c, bool) and c)
                    or (isinstance(c, str) and c in ("correct", "derived_correct"))
                )
                if is_correct:
                    correct_count -= 1
                    derived_count += 1

        total = len(steps)
        aggregated_ratio = (correct_count + 0.3 * derived_count) / total if total > 0 else 0.0

        # ── Combine with LLM's overall estimate ──
        confidence = overall.get("confidence", "uncertain")
        llm_ratio = overall.get("score_ratio", 0.0)

        try:
            llm_ratio = float(llm_ratio)
        except (ValueError, TypeError):
            llm_ratio = 0.0

        # Use the more conservative estimate:
        # - If LLM thinks higher than step analysis → trust steps (prevents inflation)
        # - If step analysis is higher → use average (LLM may see things steps miss)
        if llm_ratio > aggregated_ratio:
            ratio = aggregated_ratio
        else:
            ratio = (aggregated_ratio + llm_ratio) / 2

        # ── Apply confidence overrides ──
        if confidence == "certain_correct" and aggregated_ratio >= 0.85:
            ratio = 1.0
        elif confidence == "certain_wrong":
            ratio = min(ratio, 0.5)

        score = round(max_score * float(ratio))
        score = max(0.0, min(float(max_score), float(score)))

        return {
            "score": score,
            "confidence": confidence,
            "steps": steps,
            "note": overall.get("note", ""),
            "suggested_tags": overall.get("suggested_tags", []),
        }
