"""Multi-dimensional critical thinking assessment engine.

Two-stage pipeline:
1. Cleaning stage: normalize raw student text (fix typos, remove filler words)
2. Evaluation stage: multi-dimensional rubric assessment via LLM
"""

from typing import Optional
from .llm import LLMClient
from .rubric_loader import RubricLoader

CLEANING_SYSTEM_PROMPT = (
    '你是一位专业的文本编辑，负责将低年级学生的口语化发言转化为规范化的语义稿。\n\n'
    '【任务】\n'
    '将学生的原始发言进行语义无损清洗：\n'
    '- 纠正错别字（如"怎末"→"怎么"）\n'
    '- 过滤语气助词和填充词（如"那个""呃""然后然后"）\n'
    '- 规范标点符号和断句\n'
    '- 保留学生的原始观点、论证结构和独特表达角度\n'
    '- 不要添加学生没有说过的内容\n'
    '- 不要改变学生的核心论点或立场\n\n'
    '【输出格式】\n'
    '直接返回清洗后的规范化文本，不要加任何说明、标签或前缀。\n'
    '如果原始文本已经完全规范，直接原样返回。'
)


class AssessmentEngine:
    """Multi-dimensional critical thinking assessment with cognitive gradient support."""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient()

    async def clean(self, raw_text: str) -> str:
        """Stage 1: Clean and normalize raw student text."""
        messages = [
            {'role': 'system', 'content': CLEANING_SYSTEM_PROMPT},
            {'role': 'user', 'content': raw_text},
        ]
        try:
            result = await self.llm.chat(
                messages=messages,
                temperature=0.1,
                max_tokens=2000,
            )
            return result.strip()
        except Exception as e:
            # If cleaning fails, return original text
            return raw_text

    async def evaluate(
        self,
        rubric_loader: RubricLoader,
        cognitive_tier: str,
        topic_title: str,
        topic_type: str,
        stimulus_material: str,
        reference_arguments: list[str],
        student_text: str,
        student_grade: int,
        calibration_records: list | None = None,
    ) -> dict:
        """Stage 2: Multi-dimensional rubric evaluation."""
        system_prompt = rubric_loader.build_system_prompt(
            cognitive_tier, calibration_records
        )
        user_prompt = rubric_loader.build_user_prompt(
            topic_title=topic_title,
            topic_type=topic_type,
            stimulus_material=stimulus_material,
            reference_arguments=reference_arguments,
            student_text=student_text,
            student_grade=student_grade,
        )

        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ]

        try:
            result = await self.llm.chat_json(
                messages=messages,
                temperature=0.2,
                max_tokens=4000,
            )
            return self._normalize(result)
        except Exception as e:
            return {
                'dimension_scores': None,
                'confidence': 'uncertain',
                'reasoning': {},
                'extracted_features': {},
                'note': f'AI评估失败（{e}），请教师手动审阅。',
                'suggested_tags': [],
            }

    async def assess(
        self,
        rubric_loader: RubricLoader,
        cognitive_tier: str,
        topic_title: str,
        topic_type: str,
        stimulus_material: str,
        reference_arguments: list[str],
        raw_text: str,
        student_grade: int,
        calibration_records: list | None = None,
    ) -> dict:
        """Full two-stage assessment: clean then evaluate.

        Returns dict with keys:
            cleaned_text, dimension_scores, confidence, reasoning,
            extracted_features, note, suggested_tags
        """
        # Stage 1: Clean
        cleaned_text = await self.clean(raw_text)

        # Stage 2: Evaluate using cleaned text
        result = await self.evaluate(
            rubric_loader=rubric_loader,
            cognitive_tier=cognitive_tier,
            topic_title=topic_title,
            topic_type=topic_type,
            stimulus_material=stimulus_material,
            reference_arguments=reference_arguments,
            student_text=cleaned_text,
            student_grade=student_grade,
            calibration_records=calibration_records,
        )

        result['cleaned_text'] = cleaned_text
        return result

    @staticmethod
    def _normalize(raw: dict) -> dict:
        """Normalize LLM response into AssessmentResult shape."""
        dimension_scores = raw.get('dimension_scores', {})
        reasoning = raw.get('reasoning', {})
        extracted_features = raw.get('extracted_features', {})
        confidence = raw.get('confidence', 'uncertain')
        note = raw.get('note', '')
        suggested_tags = raw.get('suggested_tags', [])

        # Validate dimension_scores is a dict of str→str
        if not isinstance(dimension_scores, dict):
            dimension_scores = {}

        # Validate confidence value
        valid_confidence = {'certain_good', 'certain_weak', 'uncertain'}
        if confidence not in valid_confidence:
            confidence = 'uncertain'

        return {
            'dimension_scores': dimension_scores,
            'confidence': confidence,
            'reasoning': reasoning if isinstance(reasoning, dict) else {},
            'extracted_features': extracted_features if isinstance(extracted_features, dict) else {},
            'note': note,
            'suggested_tags': suggested_tags if isinstance(suggested_tags, list) else [],
        }
