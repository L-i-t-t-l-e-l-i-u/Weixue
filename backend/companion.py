"""AI-companion dialogue engine for the live-classroom flow.

The companion never talks to students directly. It generates scaffolding
questions for the TEACHER to read aloud (or rephrase), enforces the hard
boundaries from the requirements-alignment meeting (no direct answers, no
fill-in-the-blank guidance), and flags when a student answer merely echoes
the AI/teacher wording (灌输感).
"""

from typing import Optional
from grading.llm import LLMClient


SCAFFOLD_SYSTEM_PROMPT = (
    "你是一位经验丰富的思辨课教师，负责为学生的课堂发言设计\"脚手架追问\"。\n"
    "你的任务不是评价学生，而是给老师提供 1-2 条可以直接照读的追问建议。\n\n"
    "【硬性约束】\n"
    "- 只做追问和启发：提示角度、抛出反例、引导拆解，和老师在课堂上做的一样。\n"
    "- 绝对不能直接给出答案，不能替学生组织答案。\n"
    "- 禁止\"填空式\"引导：不能一步步把学生引向某个既定词（例如\"动机\"）。"
    "学生说\"动机\"\"这样做的原因\"\"出发点\"都可以，关键是出自他自己的思考。\n"
    "- 话术要具体、贴近学生刚才说的内容，不要泛泛而问。\n"
    "- 如果学生的回答已经很完整、自己说出了观点，给出鼓励性追问（拓展角度），"
    "scaffold_status 应为 ok。\n\n"
    "【复述检测】\n"
    "- 判断学生上一轮回答是否只是在复述 AI/教师的问法（例如 AI 问\"是不是有错？\""
    "学生只答\"是的\"），如果是，echo_risk 为 true，scaffold_status 为 echo_risk，"
    "并在 note 里提示老师换一种方式再问。\n\n"
    "【输出格式】严格返回 JSON：\n"
    '{"questions": ["追问1", "追问2"], "scaffold_status": "ok|continue|echo_risk", '
    '"echo_risk": true/false, "note": "一句话说明"}'
)


FALLBACK_QUESTIONS = [
    "你的理由和结论之间是不是缺了什么？要不要补充一下？",
    "如果换一个角度想，这件事还会有什么不同的看法？",
]


def build_dialogue_block(turns) -> str:
    """Render companion turns as a compact multi-round dialogue record."""
    if not turns:
        return ""
    role_label = {
        "student": "学生",
        "ai_suggestion": "AI追问建议",
        "teacher": "教师追问",
    }
    lines = ["【多轮对话记录】"]
    for i, t in enumerate(turns, 1):
        label = role_label.get(getattr(t, "role", ""), getattr(t, "role", ""))
        content = getattr(t, "content", "")
        if not content or not str(content).strip():
            continue
        turn_type = getattr(t, "turn_type", "") or ""
        prefix = f"第{i}轮 [{label}]" + ("（疑似复述）" if turn_type == "echo_risk" else "")
        lines.append(f"{prefix}：{str(content).strip()}")
    return "\n".join(lines)


class CompanionEngine:
    """Generates scaffolding suggestions and echo-risk signals for one response."""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient()

    async def suggest_turn(
        self,
        response_text: str,
        turns,
        topic_title: str,
        stimulus_material: str = "",
        student_grade: int = 4,
    ) -> dict:
        """Return {'questions': [...], 'scaffold_status': ..., 'echo_risk': bool, 'note': ...}."""
        dialogue = build_dialogue_block(turns)
        user_parts = [
            f"思辨主题：{topic_title}",
            f"学生年级：{student_grade}年级",
        ]
        if stimulus_material:
            user_parts.append(f"引导材料：\n{stimulus_material}")
        if dialogue:
            user_parts.append(dialogue)
        user_parts.append(f"学生最新回答：\n{response_text}")
        user_parts.append("请给出追问建议，并完成复述检测。")

        messages = [
            {"role": "system", "content": SCAFFOLD_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]
        try:
            raw = await self.llm.chat_json(messages, temperature=0.3, max_tokens=1000)
            return self._normalize(raw)
        except Exception:
            return self._fallback(response_text)

    @staticmethod
    def _normalize(raw: dict) -> dict:
        questions = raw.get("questions") if isinstance(raw.get("questions"), list) else []
        questions = [str(q).strip() for q in questions if str(q).strip()]
        if not questions:
            questions = FALLBACK_QUESTIONS
        scaffold_status = raw.get("scaffold_status", "ok")
        if scaffold_status not in {"ok", "continue", "echo_risk"}:
            scaffold_status = "ok"
        echo_risk = bool(raw.get("echo_risk")) or scaffold_status == "echo_risk"
        return {
            "questions": questions,
            "scaffold_status": scaffold_status,
            "echo_risk": echo_risk,
            "note": str(raw.get("note", "") or ""),
        }

    @staticmethod
    def _fallback(response_text: str) -> dict:
        text = (response_text or "").strip()
        echo_risk = False
        note = ""
        scaffold_status = "continue"
        if not text:
            echo_risk = True
            scaffold_status = "echo_risk"
            note = "学生没有说出口，建议换一种更开放的方式再问。"
        elif len(text) <= 12 and any(mark in text for mark in ("是的", "对的", "对", "嗯", "好")):
            echo_risk = True
            scaffold_status = "echo_risk"
            note = "回答过短且像是附和，建议换一种方式追问，避免学生复述问法。"
        elif len(text) >= 40:
            scaffold_status = "ok"
            note = "学生回答比较完整，可以拓展一个角度继续引导。"
        else:
            note = "回答有了雏形，可以追问理由与结论之间的连接。"
        return {
            "questions": list(FALLBACK_QUESTIONS),
            "scaffold_status": scaffold_status,
            "echo_risk": echo_risk,
            "note": note,
        }
