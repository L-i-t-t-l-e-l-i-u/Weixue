"""Seed script: populate the database with demo data for the critical thinking assessment system.

Includes:
- 3 RubricTemplate records (basic / developing / advancing)
- 1 Course with 3 DebateTopics (one per cognitive tier)
- 9 Students across grades 1-7
- Sample student responses with realistic children's language
- Pre-seeded calibration records for teacher calibration demo

Usage:
    python seed.py           # seed if DB is empty
    python seed.py --force   # wipe all data and re-seed
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timedelta
from database import (
    init_db, SessionLocal, Course, DebateTopic, Student,
    StudentResponse, RubricTemplate, CalibrationRecord, DimensionTag,
    SystemSetting, get_cognitive_tier,
)

# Chinese corner brackets used as quotation marks inside Python strings
LQ = '\u201c'  # left double quotation mark
RQ = '\u201d'  # right double quotation mark
EL = '\u2026'  # horizontal ellipsis

# ══════════════════════════════════════════════════════════════
# RUBRIC TEMPLATES
# ══════════════════════════════════════════════════════════════

# ── 五维度核心标准（企业口径，2026-08-11 确认）──────────────────────────
# 立意 / 选材 / 结构 / 语言 / 视角 为唯一核心评判标准：同一套标准 + 年级合格线；
# 明确不评：流利度、好词好句、引经据典；加分项“有自己 / 有新意”命中可升级评级。
FIVE_DIMENSIONS = ['position', 'material', 'structure', 'language', 'perspective']

FIVE_DIM_EQUAL_WEIGHTS = {d: 0.2 for d in FIVE_DIMENSIONS}

FIVE_DIM_DEFINITIONS = {
    'position': {
        'name': '立意（观点鲜明）',
        'description': '学生是否清楚表达了自己的核心看法，态度不模糊；低年级重点看“敢说、说清楚”。',
        'levels': {
            'A+': '观点鲜明、表达完整，有明确的立场和限定条件，远超同龄人清晰度',
            'A': '能清楚完整地表达自己的核心观点，态度不模糊',
            'A-': '观点基本清楚，个别表述不够精确',
            'B+': '能说出自己的想法，但表达不够完整或立场略有摇摆',
            'B': '观点模糊，需要较多推断才能理解，或前后自相矛盾',
            'B-': '无法辨识核心观点（不敢说、说不清、无意义重复）',
        },
    },
    'material': {
        'name': '选材（言之有物）',
        'description': '学生是否用具体事实、例子或材料信息支撑观点，内容不空洞。',
        'levels': {
            'A+': '提供多个具体、相关的证据或例子，并清楚说明其与观点的关系',
            'A': '提供至少一个具体、相关的证据或例子支撑观点',
            'A-': '有使用证据的意识，但证据不够具体或与观点关联较弱',
            'B+': '能引用材料信息或生活例子，但多为笼统表述',
            'B': '只有断言和笼统理由，没有具体事实或例子支撑',
            'B-': '没有任何支撑，全是主观空泛断言',
        },
    },
    'structure': {
        'name': '结构（条理清晰）',
        'description': '表达顺序是否合理，前后逻辑是否关联紧密；只看底层逻辑，不评辞藻。',
        'levels': {
            'A+': '论证链条完整严密：观点→理由→例子→小结层层递进，并能回应反面观点',
            'A': '结构清晰：观点、理由、例子衔接合理，逻辑连贯',
            'A-': '结构基本清晰，偶有逻辑跳跃但能自行拉回',
            'B+': '有先后顺序意识，但逻辑衔接不够紧密',
            'B': '东拉西扯，前后观点不连贯或自相矛盾',
            'B-': '完全碎片化，没有任何可辨识的逻辑结构',
        },
    },
    'language': {
        'name': '语言（用词准确）',
        'description': '用词是否符合语境、能否准确传达意思；只评“用词准确”，不评文采、好词好句、流利度。',
        'levels': {
            'A+': '用词精准、符合语境，能准确传达细微含义',
            'A': '用词准确、符合语境，意思传达清楚',
            'A-': '用词基本准确，个别词不达意但不影响理解',
            'B+': '部分用词不准确，需结合上下文推断',
            'B': '用词明显不当，影响意思理解',
            'B-': '用词混乱，无法理解学生想表达什么',
        },
    },
    'perspective': {
        'name': '视角（换位思考）',
        'description': '是否顾及他人感受、从多角度权衡，而不只是单一立场。',
        'levels': {
            'A+': '呈现多方立场并识别核心矛盾，提出有整合性的见解',
            'A': '能从至少两个角度思考，并尝试权衡不同立场',
            'A-': '能意识到还有其他角度，但权衡较浅',
            'B+': '提到其他可能性，但很快回到单一立场',
            'B': '只从单一视角论述，未考虑他人立场',
            'B-': '完全以自我为中心，无任何换位思考痕迹',
        },
    },
}

FIVE_DIM_NEGATIVES = {
    'position': '学生发言完全是无意义的重复或乱码，或始终不敢说出自己的想法',
    'material': '所有“事实”都是凭空编造或空泛断言（如“大家都知道”），无任何具体例子支撑',
    'structure': '论述东拉西扯、前后矛盾，或完全碎片化没有逻辑顺序',
    'language': '用词混乱、词不达意（注意：不因口语化、重复、不流畅而扣分）',
    'perspective': '从头到尾只有单一角度，完全不顾及他人感受或反面观点',
}

RUBRIC_TEMPLATES = [
    {
        'cognitive_tier': 'basic',
        'grade_range': '1-2',
        'active_dimensions': FIVE_DIMENSIONS,
        'dimension_weights': dict(FIVE_DIM_EQUAL_WEIGHTS),
        'rubric_definitions': dict(FIVE_DIM_DEFINITIONS),
        'negative_indicators': dict(FIVE_DIM_NEGATIVES),
        'prompt_template': (
            '你是一位温暖、有耐心的一二年级思辨课教师，正在评估一位低年级学生的课堂发言。\n\n'
            '【理论基础】\n'
            '- 基于Kuhn(1999)认识论发展模型，6-8岁儿童处于Absolutist阶段：认为知识是现实的直接反映，尚不能区分"观点"与"事实"\n'
            '- 本梯段评估的是批判性思维的认知前技能(CT precursor skills)，而非完整的批判性思维能力\n'
            '- 参考Byrnes & Dunbar(2014)：10岁以下儿童的工作记忆和领域知识不足以支撑元认知评估，因此我们评估的是表达完整性、简单因果连接和信息辨识等基础能力\n\n'
            '【重要评估原则】\n'
            '- 这位学生只有6-8岁，注意力容易分散，口语化表达是正常的\n'
            '- 请宽容对待错别字和语法不规范\n'
            '- 绝对不要因为学生缺乏逻辑推理、因果分析或论证深度而扣分——这些能力在此年龄段尚未发展\n'
            f'- 重点关注学生是否{LQ}说出了自己的想法{RQ}，而非想法是否{LQ}正确{RQ}\n'
            '- 企业口径（唯一核心标准）：五维度（立意/选材/结构/语言/视角）；本年级合格线是"敢说、说清楚"——观点表达完整即可视为达标，不因缺乏深度论证而扣分\n'
            '- 评语风格：温暖鼓励型，使用具体行为描述（如{LQ}你说出了自己最喜欢的动物{RQ}），避免抽象评价\n\n'
            '【评分严格性校准】\n'
            '- 评级采用六级制：A+/A/A-/B+/B/B-，其中A+仅授予真正卓越、超出年龄预期的表现\n'
            '- A级应授予确实出色的表现，不要因为学生{LQ}回答了问题{RQ}就轻易给A\n'
            '- B+/B是大多数学生的合理区间，代表{LQ}达到了基本要求但有提升空间{RQ}\n'
            '- B-仅用于确实无法提取有效信息的情况\n'
            '- 不要因为学生年龄小就一律给高分，要根据实际表现区分\n\n'
            '{DIMENSION_DEFINITIONS}\n'
            '{NEGATIVE_INDICATORS}\n\n'
            '【输出格式】请严格按以下 JSON 格式返回评估结果：\n'
            '{\n'
            '  "dimension_scores": {"维度名": "A+/A/A-/B+/B/B-"},\n'
            '  "reasoning": {"维度名": {"evidence": "原文引用", "reasoning": "评级理由"}},\n'
            '  "extracted_features": {"arguments_count": 数量, "used_because": true/false},\n'
            '  "bonus_flags": ["有自己"]或["有新意"]或["有自己","有新意"]，未命中给[],\n'
            '  "confidence": "certain_good/certain_weak/uncertain",\n'
            '  "note": "给教师的简要说明",\n'
            '  "suggested_tags": ["标签1", "标签2"]\n'
            '}\n'
            '（严格 JSON：只输出一个 JSON 对象，不要 Markdown 代码块；字符串内的换行请用 \\n 转义）\n\n'
            '{CALIBRATION_EXAMPLES}'
        ),
    },
    {
        'cognitive_tier': 'developing',
        'grade_range': '3-5',
        'active_dimensions': FIVE_DIMENSIONS,
        'dimension_weights': dict(FIVE_DIM_EQUAL_WEIGHTS),
        'rubric_definitions': dict(FIVE_DIM_DEFINITIONS),
        'negative_indicators': dict(FIVE_DIM_NEGATIVES),
        'prompt_template': (
            '你是一位善于引导探索的三至五年级思辨课教师，正在评估一位中年级学生的课堂发言或习作。\n\n'
            '【理论基础】\n'
            '- 基于Kuhn(1999)认识论发展模型，8-11岁学生处于Absolutist→Multiplist过渡期：开始能给出理由支撑观点，但倾向于认为"每个问题有正确答案"，尚不能评估不同论证的相对质量\n'
            '- 此阶段学生已具备基本的因果推理能力，但尚不能进行抽象逻辑分析或识别论证中的隐藏假设\n\n'
            '【重要评估原则】\n'
            f'- 请重点关注学生是否{LQ}围绕主题展开讨论{RQ}和{LQ}是否给出了理由{RQ}\n'
            '- 企业口径（唯一核心标准）：五维度（立意/选材/结构/语言/视角）；本年级合格线是"围绕主题给出具体理由"——理由充分、不跑题即可视为达标\n'
            '- 不要评测学生能否识别论证中的隐藏假设或进行元认知反思——这些是高年级能力\n'
            '- 适当宽容口语化表达和轻微跑题\n'
            f'- 评语风格：引导探索型，指出{LQ}你已经在做的好事{RQ}并暗示{LQ}下一步可以试试{EL}{EL}{RQ}\n\n'
            '【评分严格性校准】\n'
            '- 评级采用六级制：A+/A/A-/B+/B/B-，其中A+仅授予远超同龄水平的卓越表现\n'
            '- A级应授予确实出色的表现：论证清晰有力、紧扣主题、逻辑严密\n'
            '- B+/B是大多数学生的合理区间，代表{LQ}有思考但不够成熟{RQ}\n'
            '- B-仅用于完全无法理解核心观点或完全跑题的情况\n'
            '- 不要因为学生写了很长篇幅就给高分，要看内容质量而非字数\n\n'
            '{DIMENSION_DEFINITIONS}\n'
            '{NEGATIVE_INDICATORS}\n\n'
            '【输出格式】请严格按以下 JSON 格式返回评估结果：\n'
            '{\n'
            '  "dimension_scores": {"维度名": "A+/A/A-/B+/B/B-"},\n'
            '  "reasoning": {"维度名": {"evidence": "原文引用", "reasoning": "评级理由"}},\n'
            '  "extracted_features": {"arguments_count": 数量, "causal_connectors": [], "off_topic_ratio": 0.0},\n'
            '  "bonus_flags": ["有自己"]或["有新意"]或["有自己","有新意"]，未命中给[],\n'
            '  "confidence": "certain_good/certain_weak/uncertain",\n'
            '  "note": "给教师的简要说明",\n'
            '  "suggested_tags": ["标签1", "标签2"]\n'
            '}\n'
            '（严格 JSON：只输出一个 JSON 对象，不要 Markdown 代码块；字符串内的换行请用 \\n 转义）\n\n'
            '{CALIBRATION_EXAMPLES}'
        ),
    },
    {
        'cognitive_tier': 'advancing',
        'grade_range': '6-7',
        'active_dimensions': FIVE_DIMENSIONS,
        'dimension_weights': dict(FIVE_DIM_EQUAL_WEIGHTS),
        'rubric_definitions': dict(FIVE_DIM_DEFINITIONS),
        'negative_indicators': dict(FIVE_DIM_NEGATIVES),
        'prompt_template': (
            '你是一位学术导向的六至七年级思辨课教师，正在评估一位高年级学生的课堂发言或习作。\n\n'
            '【理论基础】\n'
            '- 基于Kuhn(1999)认识论发展模型，11-13岁学生处于Multiplist→Evaluativist过渡期：开始认识到不同观点可以用证据和逻辑来评估比较，而非"所有观点都一样有道理"\n'
            '- 参考Osborne(2004)论证等级模型：rebuttal意识是区分论证质量的核心分水岭\n'
            '- 参考McNeill(2011) CER框架：论证由Claim(主张)、Evidence(证据)、Reasoning(推理)三部分组成\n\n'
            '【重要评估原则】\n'
            f'- 全面评估其论证质量：不仅看{LQ}有没有理由{RQ}，更要看{LQ}理由是否有力{RQ}{LQ}是否考虑了反面{RQ}{LQ}是否识别了矛盾{RQ}\n'
            '- 企业口径（唯一核心标准）：五维度（立意/选材/结构/语言/视角）；本年级合格线是"逻辑论证严谨度"——理由充分、反驳有力即视为达标\n'
            '- 使用苏格拉底式追问的评语风格：肯定其亮点的同时，用反问引导学生思考更深层的问题\n'
            '- 对篇幅长但内容空洞的作答，不要因为字数多而给高分\n'
            '- 对篇幅短但角度独特的作答，应识别其思维独创性\n\n'
            '【评分严格性校准】\n'
            '- 评级采用六级制：A+/A/A-/B+/B/B-，请严格区分各等级\n'
            '- A+仅授予展现出真正批判性思维和元认知能力的杰出表现，绝大多数学生不应获得A+\n'
            '- A级应授予论证有力、多角度思考、有自我反思的优秀表现\n'
            '- B+/B是大多数学生的合理区间，代表{LQ}有基本的论证意识但深度不足{RQ}\n'
            '- B-仅用于论述完全缺乏实质内容或思维封闭的情况\n'
            '- 特别注意：篇幅长≠质量好，空泛的断言式长文应得B甚至B-\n'
            '- 反驳硬门槛：如果学生完全没有考虑反面观点或替代解释，"结构"与"视角"不得高于B+\n\n'
            '{DIMENSION_DEFINITIONS}\n'
            '{NEGATIVE_INDICATORS}\n\n'
            '【输出格式】请严格按以下 JSON 格式返回评估结果：\n'
            '{\n'
            '  "dimension_scores": {"维度名": "A+/A/A-/B+/B/B-"},\n'
            '  "reasoning": {"维度名": {"evidence": "原文引用", "reasoning": "评级理由"}},\n'
            '  "extracted_features": {"arguments_count": 数量, "counter_arguments": 数量, "perspectives": 数量, "logical_connectors": []},\n'
            '  "bonus_flags": ["有自己"]或["有新意"]或["有自己","有新意"]，未命中给[],\n'
            '  "confidence": "certain_good/certain_weak/uncertain",\n'
            '  "note": "给教师的简要说明",\n'
            '  "suggested_tags": ["标签1", "标签2"]\n'
            '}\n'
            '（严格 JSON：只输出一个 JSON 对象，不要 Markdown 代码块；字符串内的换行请用 \\n 转义）\n\n'
            '{CALIBRATION_EXAMPLES}'
        ),
    },
]

# ══════════════════════════════════════════════════════════════
# COURSE & DEBATE TOPICS
# ══════════════════════════════════════════════════════════════

COURSE = {
    'title': '动物应该养在动物园吗？',
    'class_name': '思辨提升班（混龄）',
    'grade_level': 4,
}

TOPICS = [
    {
        'title': '如果你是一只被救助的受伤老鹰，康复后你愿意被放回野外还是留在动物园？请说明理由。',
        'topic_type': 'dilemma',
        'cognitive_tier': 'basic',
        'stimulus_material': (
            '一只老鹰在山上受伤了，被人送到了动物救助站。经过治疗，老鹰的伤好了。'
            '现在有两个选择：把它放回大自然，让它重新飞翔；或者让它留在动物园里，'
            '因为动物园里有吃的、有医生，很安全。如果你是这只老鹰，你会怎么选？'
        ),
        'reference_arguments': [
            '放回野外：老鹰属于天空，自由是最重要的',
            '放回野外：它已经康复了，可以自己捕食',
            '留在动物园：野外很危险，可能再次受伤',
            '留在动物园：动物园有稳定的食物来源',
            '留在动物园：在动物园还能让小朋友看到老鹰，学到知识',
        ],
        'max_score': 10,
    },
    {
        'title': f'{LQ}动物园的存在主要是为了保护濒危动物{RQ}——这是事实还是观点？你怎么看？',
        'topic_type': 'fact_opinion',
        'cognitive_tier': 'developing',
        'stimulus_material': (
            '有人说，动物园最重要的任务是保护那些快要灭绝的动物，比如大熊猫、东北虎。'
            '也有人说，动物园其实是为了让人观赏、赚钱。'
            '还有人认为，动物园对动物的教育意义最重要——让城里的孩子认识动物。'
            f'请你想一想：{LQ}动物园的存在主要是为了保护濒危动物{RQ}，这句话是事实还是观点？'
        ),
        'reference_arguments': [
            f'这是观点：因为动物园还有观赏、教育、科研等多种功能，说{LQ}主要是保护{RQ}是一种价值判断',
            '部分事实：确实有很多动物园参与了濒危动物繁殖项目',
            f'区分方法：事实是可以验证的（如{LQ}某动物园繁殖了多少只大熊猫{RQ}），观点是带有{LQ}应该{RQ}{LQ}主要{RQ}等价值判断的',
        ],
        'max_score': 10,
    },
    {
        'title': f'有人说{LQ}去过动物园的孩子更爱护动物{RQ}，你觉得这个说法有道理吗？为什么？',
        'topic_type': 'causal',
        'cognitive_tier': 'advancing',
        'stimulus_material': (
            '一项调查显示，78%的家长认为带孩子去动物园有助于培养孩子的爱心。'
            f'但动物保护组织的一位专家表示：{LQ}仅靠看动物园里的动物，不足以让孩子真正理解动物保护。{RQ}'
            f'还有人说：{LQ}看了笼子里的动物，孩子反而觉得动物就是被关着给人看的。{RQ}'
            f'请分析{LQ}去过动物园的孩子更爱护动物{RQ}这个因果关系是否成立。'
        ),
        'reference_arguments': [
            '支持因果：接触动物能激发好奇心和同理心',
            '支持因果：看到真实的动物比看书本印象更深',
            '质疑因果：相关性不等于因果性——爱护动物的孩子可能本来就更想去动物园',
            '质疑因果：动物园的展示方式（笼中动物）可能传递错误的动物观',
            f'深层分析：取决于动物园的教育质量和参观方式，而非{LQ}去过{RQ}本身',
        ],
        'max_score': 10,
    },
]

# ══════════════════════════════════════════════════════════════
# STUDENTS (9 students, distributed across 3 cognitive tiers)
# ══════════════════════════════════════════════════════════════

STUDENTS = [
    # ── basic tier (1-2年级) ──────────────────────────────

    {
        'name': '小雨',
        'grade': 1,
        'responses': {
            1: (
                '嗯……我想让它……飞走！因为老鹰就是应该飞的嘛。'
                '老鹰飞起来可帅了！我看过老鹰飞的那个视频，就是……翅膀特别大。'
                '然后然后……如果在动物园里的话，老鹰就飞不了了，只能走来走去，好可怜的。'
                '所以我觉得应该放它走。但是……但是它万一又受伤了怎末办呢……'
                '嗯……那……那还是放它走吧，因为飞比较重要。'
            ),
        },
    },
    {
        'name': '豆豆',
        'grade': 2,
        'responses': {
            1: (
                '我选留在动物园。因为动物园有人喂它吃东西，不用自己找吃的。'
                '而且外面有大灰狼……不对，老鹰不怕大灰狼。'
                '嗯，但是外面可能没有吃的，它受伤了就是找不到吃的才受伤的嘛。'
                '动物园有医生，受伤了可以看医生。'
                '而且我在动物园看到过老鹰！很酷的！别的小朋友也能看到。'
            ),
        },
    },
    {
        'name': '萌萌',
        'grade': 2,
        'responses': {
            1: (
                '我想放它走……但是不是直接放走！'
                '就是……先让它飞一下试试，看它还会不会自己抓东西吃。'
                '如果会抓了就放走，如果不会就再养一段时间。'
                '就像我学骑自行车一样，先有辅助轮，后来拆掉了就会骑了。'
                '老鹰也应该先练习一下再飞走。'
            ),
        },
    },

    # ── developing tier (3-5年级) ────────────────────────────

    {
        'name': '小明',
        'grade': 4,
        'responses': {
            2: (
                f'我觉得这是一个观点，不是事实。因为{LQ}主要是{RQ}这三个字就是在说哪个更重要，'
                '每个人觉得重要的东西不一样。比如动物园的园长可能觉得保护最重要，'
                '但卖门票的人可能觉得让人来参观赚钱最重要。'
                '不过动物园确实做了保护工作，比如大熊猫的繁殖项目，这个是事实。'
                '所以这句话里面有一部分事实，但整体上是一个观点。'
            ),
        },
    },
    {
        'name': '婷婷',
        'grade': 3,
        'responses': {
            2: (
                '嗯……我觉得是事实吧。因为动物园里确实有很多快要灭绝的动物。'
                '比如大熊猫，就是因为动物园在保护它们才没有灭绝的。'
                '所以动物园的存在就是为了保护它们。'
                '不过……有些动物园里面也有不是濒危的动物，比如猴子和老虎什么的。'
                '那这些可能不是为了保护的。'
            ),
        },
    },
    {
        'name': '浩浩',
        'grade': 5,
        'responses': {
            2: (
                f'这是一个观点。因为{LQ}主要{RQ}这个词代表了一种价值排序。'
                '事实上动物园同时做好几件事：保护濒危动物、供人参观、做科学研究、还有教育。'
                f'至于哪个是{LQ}主要的{RQ}，取决于你从谁的角度看。'
                '从动物保护者的角度，保护是主要的。从商业角度，赚钱是主要的。'
                '从教育的角度，让孩子认识动物是主要的。'
                f'所以不能简单地说{LQ}主要是什么{RQ}，得先问{LQ}对谁来说主要{RQ}。'
            ),
        },
    },

    # ── advancing tier (6-7年级) ─────────────────────────────

    {
        'name': '小杰',
        'grade': 6,
        'responses': {
            3: (
                '这个因果关系不完全成立。\n\n'
                f'{LQ}去过动物园{RQ}和{LQ}更爱护动物{RQ}之间可能存在相关性，'
                '但不一定是因果关系。\n\n'
                '首先，有可能是反向因果：本来就爱护动物的家庭更愿意带孩子去动物园，'
                '而不是去动物园导致了爱护动物。这就好比说买书多的家庭孩子成绩好，'
                '不是因为买书导致成绩好，而是重视教育的家庭既买书又抓学习。\n\n'
                '其次，即使有因果关系，也要看动物园的质量。如果动物园只是把动物关在笼子里，'
                f'孩子看到的可能是{LQ}动物就是被关着给人看的{RQ}，这反而可能削弱对动物的尊重。\n\n'
                '不过我也承认，对于城里从没见过真实动物的孩子来说，'
                '亲眼看到大象比看书上的图片确实更有冲击力。'
                f'所以我认为关键在于参观的方式和质量，而不是{LQ}去过{RQ}这个行为本身。'
            ),
        },
    },
    {
        'name': '佳怡',
        'grade': 7,
        'responses': {
            3: (
                '我觉得不能一概而论。\n\n'
                '一方面，动物园如果设计得好，确实能成为动物保护教育的入口。'
                '比如有些动物园会讲解动物面临的威胁、栖息地破坏等问题，'
                '这种有教育深度的参观体验可能真的能培养孩子的保护意识。\n\n'
                f'但另一方面，78%的家长{LQ}认为{RQ}有帮助，这个调查本身就可能有偏差——'
                '愿意花钱带孩子去动物园的家长，本身就更重视自然教育，'
                f'他们的孩子{LQ}更爱护动物{RQ}可能是家庭教育导致的。\n\n'
                f'而且{LQ}爱护动物{RQ}怎么定义呢？是看到流浪猫会心疼？还是愿意为保护动物捐款？'
                '还是日常生活中不吃野生动物？这个概念如果没定义清楚，'
                '那个78%的数据本身就不可靠。\n\n'
                '我的结论是：这个说法有一定的合理性，但把复杂的因果关系简化为'
                f'{LQ}去过=更爱护{RQ}是不严谨的。更准确的说法应该是：'
                f'{LQ}高质量的动物园教育体验，结合家庭引导，有助于培养孩子的动物保护意识。{RQ}'
            ),
        },
    },
    {
        'name': '大伟',
        'grade': 6,
        'responses': {
            3: (
                '这个说法挺有道理的。因为你去动物园就能看到真实的动物，看到之后就会觉得动物很可爱，'
                '然后就会想要保护它们。就像你看到一只可爱的小猫，你就会想照顾它一样。'
                '而且很多动物园都有讲解员告诉你这些动物的故事，'
                '你知道了它们的生活习性之后就会更爱护它们。'
                '我觉得那些没去过动物园的小孩可能就不知道动物长什么样，'
                '所以就不会那么爱护动物。我小时候去过动物园之后就开始喜欢动物了，'
                '现在我家里养了两只猫，我都特别爱护它们。'
                '所以去过动物园确实能让人更爱护动物。'
            ),
        },
    },
]

# ══════════════════════════════════════════════════════════════
# TAGS (base dimension tag library)
# ══════════════════════════════════════════════════════════════

TAG_SEEDS = [
    '观点表达清晰', '能使用因果连接词', '论据具体有力',
    '考虑了多方立场', '展示了自我反思', '能区分事实与观点',
    '论述缺乏论据支撑', '能引用具体证据', '跑题或答非所问',
    '仅有断言无推理', '未考虑反面论据', '论点过于笼统',
    '能用完整句表达感受', '能区分材料与想象', '口语化严重但观点独特',
    '因果链条不完整', '部分跑题但能自行拉回', '开始尝试多角度思考',
    '识别了隐藏假设', '论证有深度', '篇幅长但内容空洞',
    '反驳角度独特', '概念界定意识强',
    ('动物园', 'teacher', 1),
    ('结构待加强', 'teacher', 1),
    ('紧扣主题', 'teacher', 1),
    ('语言待精确', 'teacher', 1),
]

# ══════════════════════════════════════════════════════════════
# CALIBRATION RECORDS (pre-seeded for demo)
# ══════════════════════════════════════════════════════════════

CALIBRATION_SEEDS = [
    {
        'teacher_id': 'default',
        'ai_original_scores': {'position': 'B+', 'material': 'B+', 'structure': 'B', 'language': 'B+', 'perspective': 'B+'},
        'teacher_final_scores': {'position': 'B+', 'material': 'B+', 'structure': 'A', 'language': 'B+', 'perspective': 'B+'},
        'modifications': [
            {'dimension': 'structure', 'from_rating': 'B+', 'to_rating': 'A', 'reason': '虽然论据不多，但反驳角度很独特，逻辑链条值得更高的结构评分'},
        ],
        'note': '这个学生虽然论述不长，但切入角度很好，不应因篇幅短而降分',
        'student_grade': 4,
    },
    {
        'teacher_id': 'default',
        'ai_original_scores': {'position': 'A', 'material': 'B+', 'structure': 'B+', 'language': 'A-', 'perspective': 'B+'},
        'teacher_final_scores': {'position': 'A', 'material': 'A', 'structure': 'B+', 'language': 'A-', 'perspective': 'B+'},
        'modifications': [
            {'dimension': 'material', 'from_rating': 'B+', 'to_rating': 'A', 'reason': '学生使用了具体的生活案例作为论据，这比引用数据更有说服力'},
        ],
        'note': '生活案例和统计数据一样有价值，不要因为没用数字就低估论据质量',
        'student_grade': 7,
    },
    {
        'teacher_id': 'default',
        'ai_original_scores': {'position': 'B', 'material': 'B+', 'structure': 'B', 'language': 'B', 'perspective': 'B+'},
        'teacher_final_scores': {'position': 'B+', 'material': 'B+', 'structure': 'B+', 'language': 'B', 'perspective': 'B+'},
        'modifications': [
            {'dimension': 'position', 'from_rating': 'B', 'to_rating': 'B+', 'reason': '虽然表达不太流畅，但能看出核心观点是什么'},
            {'dimension': 'structure', 'from_rating': 'B', 'to_rating': 'B+', 'reason': f'学生用了{LQ}因为{RQ}这个词，说明有逻辑连接的意识'},
        ],
        'note': '这个学生表达比较吃力，但思维火花值得肯定，不要因为表达问题过度扣分',
        'student_grade': 3,
    },
    {
        'teacher_id': 'default',
        'ai_original_scores': {'position': 'A', 'material': 'B', 'structure': 'B', 'language': 'A-', 'perspective': 'B'},
        'teacher_final_scores': {'position': 'A', 'material': 'B-', 'structure': 'B-', 'language': 'A-', 'perspective': 'B'},
        'modifications': [
            {'dimension': 'material', 'from_rating': 'B', 'to_rating': 'B-', 'reason': f'全文都是{LQ}我觉得{RQ}{LQ}大家都知道{RQ}式断言，没有实质性论据'},
            {'dimension': 'structure', 'from_rating': 'B', 'to_rating': 'B-', 'reason': '从头到尾只有一个角度的重复陈述'},
        ],
        'note': '篇幅长不等于质量好，这篇论述表面流畅但缺乏实质内容',
        'student_grade': 6,
    },
]

# ══════════════════════════════════════════════════════════════
# TEACHER REVIEWS (demo state: every response has been reviewed)
# Seeded so a fresh `python seed.py --force` yields a complete demo —
# comment generation requires at least one teacher-reviewed topic.
# Keyed by student id; keys match the STUDENTS list above.
# ══════════════════════════════════════════════════════════════

TEACHER_REVIEWS = {
    1: {
        'topic_id': 1,
        'teacher_dimension_scores': {'position': 'B+', 'material': 'A-', 'structure': 'B+', 'language': 'A-', 'perspective': 'A-'},
        'teacher_tags': ['能自发考虑反方观点', '情感投入丰富', '有简单逻辑连接'],
        'ai_bonus_flags': ['有新意'],
        'teacher_note': '',
        'teacher_rating': 'good',
        'teacher_confidence_override': None,
    },
    2: {
        'topic_id': 1,
        'teacher_dimension_scores': {'position': 'A-', 'material': 'B+', 'structure': 'B+', 'language': 'B+', 'perspective': 'B+'},
        'teacher_tags': ['有解释意图', '选材意识萌芽', '口语化表达', '语言待精确'],
        'teacher_note': '',
        'teacher_rating': 'guide',
        'teacher_confidence_override': None,
    },
    3: {
        'topic_id': 1,
        'teacher_dimension_scores': {'position': 'A', 'material': 'B', 'structure': 'A-', 'language': 'A', 'perspective': 'B+'},
        'teacher_tags': ['观点表达清晰', '选材意识待发展'],
        'teacher_note': '',
        'teacher_rating': 'good',
        'teacher_confidence_override': None,
    },
    4: {
        'topic_id': 2,
        'teacher_dimension_scores': {'position': 'A', 'material': 'A', 'structure': 'A-', 'language': 'A-', 'perspective': 'B+'},
        'teacher_tags': ['结构清晰', '选材具体', '论证有深度'],
        'ai_bonus_flags': ['有自己'],
        'teacher_note': '',
        'teacher_rating': 'good',
        'teacher_confidence_override': None,
    },
    5: {
        'topic_id': 2,
        'teacher_dimension_scores': {'position': 'A-', 'material': 'A-', 'structure': 'A-', 'language': 'A', 'perspective': 'B+'},
        'teacher_tags': ['自我质疑', '事实与观点', '选材具体', '结构清晰'],
        'teacher_note': '选材尚可',
        'teacher_rating': 'guide',
        'teacher_confidence_override': None,
    },
    6: {
        'topic_id': 2,
        'teacher_dimension_scores': {'position': 'A', 'material': 'A', 'structure': 'A', 'language': 'A-', 'perspective': 'A+'},
        'teacher_tags': ['结构清晰', '视角多元分析', '紧扣主题'],
        'ai_bonus_flags': ['有新意'],
        'teacher_note': '紧扣主题',
        'teacher_rating': 'good',
        'teacher_confidence_override': None,
    },
    7: {
        'topic_id': 3,
        'teacher_dimension_scores': {'position': 'A', 'material': 'A', 'structure': 'B+', 'language': 'A-', 'perspective': 'A'},
        'teacher_tags': ['多角度分析', '结构清晰', '结构待加强'],
        'teacher_note': '',
        'teacher_rating': 'guide',
        'teacher_confidence_override': None,
    },
    8: {
        'topic_id': 3,
        'teacher_dimension_scores': {'position': 'A', 'material': 'A', 'structure': 'A-', 'language': 'A-', 'perspective': 'A'},
        'teacher_tags': ['结构清晰', '概念分析', '反驳意识待加强', '动物园'],
        'teacher_note': '很好的逻辑结构能力',
        'teacher_rating': 'good',
        'teacher_confidence_override': None,
    },
    9: {
        'topic_id': 3,
        'teacher_dimension_scores': {'position': 'B+', 'material': 'B', 'structure': 'B', 'language': 'B+', 'perspective': 'B'},
        'teacher_tags': ['单一视角', '需加强逻辑连接', '个人经验主导', '缺乏反驳', '论证意识初现'],
        'teacher_note': '',
        'teacher_rating': 'echo',
        'teacher_confidence_override': None,
    },
}

# ══════════════════════════════════════════════════════════════
# SEED FUNCTION
# ══════════════════════════════════════════════════════════════

def seed(force=False):
    init_db()
    db = SessionLocal()

    if db.query(Course).count() > 0:
        if not force:
            print("Database already has data. Use --force to wipe and re-seed.")
            db.close()
            return
        print("Wiping existing data...")
        db.query(CalibrationRecord).delete()
        db.query(StudentResponse).delete()
        db.query(Student).delete()
        db.query(DebateTopic).delete()
        db.query(DimensionTag).delete()
        db.query(Course).delete()
        db.query(RubricTemplate).delete()
        db.query(SystemSetting).filter(SystemSetting.key.like("demo_%")).delete()
        db.commit()

    # Create Rubric Templates. Reuse existing rows (keyed by cognitive_tier) so
    # seeding still works on a database that already has the global templates —
    # e.g. after a real-mode purge removed only the demo course.
    template_map = {}
    existing_templates = {
        t.cognitive_tier: t for t in db.query(RubricTemplate).all()
    }
    for t_data in RUBRIC_TEMPLATES:
        tier = t_data['cognitive_tier']
        if tier in existing_templates:
            template_map[tier] = existing_templates[tier]
            print(f"  Reused rubric template: {tier} ({t_data['grade_range']})")
            continue
        template = RubricTemplate(**t_data)
        db.add(template)
        db.flush()
        template_map[tier] = template
        print(f"  Created rubric template: {tier} ({t_data['grade_range']})")

    # Create Course
    course = Course(**COURSE)
    db.add(course)
    db.flush()
    cid = course.id

    # Create Debate Topics
    for i, t_data in enumerate(TOPICS):
        tier = t_data['cognitive_tier']
        topic = DebateTopic(
            course_id=cid,
            order=i + 1,
            rubric_template_id=template_map[tier].id,
            **{k: v for k, v in t_data.items() if k != 'rubric_template_id'},
        )
        db.add(topic)
    db.flush()

    topics = db.query(DebateTopic).filter(
        DebateTopic.course_id == cid
    ).order_by(DebateTopic.order).all()
    topic_map = {t.order: t for t in topics}

    # Create Students + Responses
    for s_data in STUDENTS:
        student = Student(
            course_id=cid,
            name=s_data['name'],
            grade=s_data['grade'],
        )
        db.add(student)
        db.flush()

        tier = get_cognitive_tier(s_data['grade'])
        print(f"  Created student: {s_data['name']} (grade {s_data['grade']}, tier={tier})")

        for topic_order, raw_text in s_data['responses'].items():
            topic = topic_map.get(topic_order)
            if not topic:
                continue
            resp = StudentResponse(
                student_id=student.id,
                topic_id=topic.id,
                raw_text=raw_text,
                cleaned_text='',
            )
            db.add(resp)
            review = TEACHER_REVIEWS.get(student.id)
            if review and review['topic_id'] == topic_order:
                resp.teacher_dimension_scores = review['teacher_dimension_scores']
                resp.teacher_tags = review['teacher_tags']
                resp.ai_bonus_flags = review.get('ai_bonus_flags', [])
                resp.teacher_note = review['teacher_note']
                resp.teacher_confidence_override = review['teacher_confidence_override']
                resp.teacher_rating = review.get('teacher_rating', '')
                resp.teacher_reviewed = True

    # Seed Dimension Tags
    for tag_seed in TAG_SEEDS:
        if isinstance(tag_seed, tuple):
            tag_name, source, use_count = tag_seed
        else:
            tag_name, source, use_count = tag_seed, 'base', 0
        t = DimensionTag(course_id=cid, name=tag_name, source=source, use_count=use_count)
        db.add(t)

    # Seed Calibration Records
    db.flush()
    all_responses = db.query(StudentResponse).all()
    resp_by_grade = {}
    for r in all_responses:
        st = db.get(Student, r.student_id)
        if st:
            grade = st.grade
            if grade not in resp_by_grade:
                resp_by_grade[grade] = []
            resp_by_grade[grade].append(r)

    for i, cal_data in enumerate(CALIBRATION_SEEDS):
        grade = cal_data['student_grade']
        responses = resp_by_grade.get(grade, [])
        if not responses:
            responses = all_responses
        target_resp = responses[i % len(responses)]

        record = CalibrationRecord(
            response_id=target_resp.id,
            teacher_id=cal_data['teacher_id'],
            ai_original_scores=cal_data['ai_original_scores'],
            teacher_final_scores=cal_data['teacher_final_scores'],
            modifications=cal_data['modifications'],
            note=cal_data['note'],
            created_at=datetime.utcnow() - timedelta(days=len(CALIBRATION_SEEDS) - i),
        )
        db.add(record)

    # Mark this course as demo/seed data so switching to real ASR mode can
    # purge exactly the demo content (never real teacher data).
    marker = db.get(SystemSetting, "demo_course_id")
    if marker is None:
        marker = SystemSetting(key="demo_course_id", value=str(cid))
        db.add(marker)
    else:
        marker.value = str(cid)

    db.commit()

    print(f"\nSeeded successfully:")
    print(f"  - {len(RUBRIC_TEMPLATES)} rubric templates")
    print(f"  - 1 course: {COURSE['title']}")
    print(f"  - {len(TOPICS)} debate topics")
    print(f"  - {len(STUDENTS)} students")
    print(f"  - {len(TAG_SEEDS)} dimension tags")
    print(f"  - {len(CALIBRATION_SEEDS)} calibration records")
    print(f"  - {len(TEACHER_REVIEWS)} teacher-reviewed responses")
    db.close()


if __name__ == "__main__":
    force = "--force" in sys.argv
    seed(force=force)
