# 维学思辨星 — 少儿思辨能力认知自适应评估系统

面向 1-7 年级思辨课堂的 AI 辅助评估系统。基于 Kuhn（1999）认识论发展模型，为不同认知梯段的学生匹配差异化评估维度，让 AI 承担多维度评分和评语草稿等机械劳动，教师专注于教学判断和个性化反馈。

**在线演示**：[https://l-i-t-t-l-e-l-i-u.github.io/weixue/](https://l-i-t-t-l-e-l-i-u.github.io/weixue/)

## 问题与立场

当前 AI 教育产品普遍追求"全自动批改"——AI 读学生作答、AI 打分、AI 写评语，教师沦为旁观者。但研究表明，AI 过度接管评价环节会削弱学生的深度学习（CEPR, 26,811 名学生样本），更关键的是：思辨能力的发展本身就不是一个可以全自动量化的过程。

我们的立场是 **AI 退后一步**：AI 负责结构化分析和草稿生成，在每个主观评价节点设置决策门，最终判断权始终在教师手中。这不是"人机协作"的套话——系统的每一个设计决策都围绕这个原则展开。

## 三个核心创新

### 1. 认知梯度 Rubric（Cognitive Gradient Rubric）

抛弃"所有学生用同一套评分标准"的粗暴做法。基于 Kuhn（1999）的 Realist → Absolutist → Multiplist → Evaluativist 四阶段认识论模型，将 1-7 年级划分为三个认知梯段，每个梯段匹配不同的评估维度和行为锚点：

| 梯段 | 年级 | 核心维度 | 理论依据 |
|------|------|----------|----------|
| 基础层 | 1-2 年级 | 清晰性、解释力、证据意识 | Byrnes & Dunbar (2014)：CT 前技能阶段 |
| 发展层 | 3-5 年级 | 清晰性、相关性、因果推理、证据使用 | Absolutist → Multiplist 过渡期 |
| 进阶层 | 6-7 年级 | 清晰性、相关性、论证质量、深度广度、反思调节 | Multiplist → Evaluativist 过渡期 |

每个维度下设 A+/A/A-/B+/B/B- 六级行为锚点，由 `rubric_loader.py` 在评估时动态组装为完整 prompt。论证质量维度引入 McNeill CER 框架 + Osborne 5 级评分，rebuttal 缺失硬性限制不超过 B+。

### 2. 双层评估流水线（Two-Layer Pipeline）

借鉴 NLP 数据清洗的 decoupling 思想，将评估拆分为两个解耦阶段：

- **Layer 1 — 文本清洗**：去除口语填充词（"嗯""那个""就是"）、修复错别字、规范化标点，产出 `cleaned_text`。保留原始 `raw_text` 供教师回溯。
- **Layer 2 — 维度评估**：基于清洗后的文本，调用认知梯度 rubric 进行多维度评分、推理链生成、特征提取和标签推荐。

这种解耦使每一层可以独立迭代——未来接入语音识别或 OCR 时只需替换 Layer 1，评估逻辑完全不受影响。

### 3. 教师校准记忆（Teacher Calibration Memory）

AI 评估不应该"忘掉"教师的修正偏好。每当教师在批改页覆盖 AI 评分时，系统自动记录差异（AI 原评分 → 教师终评分 + 理由），存入 `calibration_records` 表。下次评估新回答时，`rubric_loader` 从数据库中取最近 10 条校准记录，以紧凑格式注入 LLM prompt 的 few-shot 区域：

```
校准1  AI评分：清晰性A、解释力A-、证据意识B+
       教师修正：清晰性B+、解释力A-、证据意识A-
       教师理由：表达流畅但观点不够明确

校准2  AI评分：论证质量A-、深度广度B+、反思调节B+
       教师修正：论证质量B、深度广度B、反思调节B
       教师理由：缺乏证据支撑，多为个人断言
```

这不是量化蒸馏（"平均上调 0.5 级"对 LLM 没有意义），而是将教师的判断模式以自然语言形式传递给 AI，使评分倾向逐步向教师靠拢。

## 功能模块

- **智能评估**：AI 按认知梯度 rubric 批量评估，每个维度给出六级评级 + 推理链 + 建议标签。教师逐份审阅，可覆盖任意维度的评分。
- **评语生成**：基于教师确认的评分、标签和批注，LLM 生成个性化评语草稿。教师编辑后发送，支持批量生成。
- **备课辅助**：按辩题聚合评估数据，识别班级薄弱维度和低分学生，辅助讲评课备课。
- **学情报告**：班级层面的多维分析报告，含各学生综合得分、维度雷达图和 Top 标签统计。
- **标签库**：管理评估标签，支持合并、重命名、删除。标签来源分为教研预设（base）、AI 生成（ai_new）和教师手动添加（teacher）。

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端 | FastAPI + Uvicorn + SQLAlchemy |
| 数据库 | SQLite |
| LLM | OpenAI SDK（兼容 DashScope / DeepSeek / OpenAI） |
| 前端 | React 18 + Vite + Zustand + Tailwind CSS |
| 部署 | GitHub Pages（纯前端 demo 模式）/ FastAPI + 前端静态托管 |

## 项目结构

```
Weixue/
├── backend/
│   ├── main.py                # FastAPI 路由（API + 静态文件托管）
│   ├── database.py            # SQLAlchemy 数据模型
│   ├── schemas.py             # Pydantic 请求/响应模型
│   ├── seed.py                # 演示数据填充
│   ├── grading/
│   │   ├── evaluator.py       # 认知梯度评估引擎
│   │   ├── rubric_loader.py   # Rubric 模板加载 + prompt 组装 + 校准注入
│   │   ├── engine.py          # 文本清洗 + 特征提取
│   │   └── llm.py             # LLM 客户端适配器
│   └── data/                  # SQLite 数据库
├── frontend/
│   ├── src/
│   │   ├── App.jsx            # 根组件（5 Tab 页）
│   │   ├── api/
│   │   │   ├── client.js      # API 客户端（自动切换 demo/真实模式）
│   │   │   └── demoClient.js  # 纯前端 demo 数据源
│   │   ├── pages/             # 5 个功能页面
│   │   └── stores/            # Zustand 状态管理
│   └── package.json
├── papers/                    # 核心参考文献
│   ├── Kuhn_1999_*.pdf        # 认识论发展阶段模型
│   ├── Byrnes_Dunbar_2014_*.pdf  # CT 前技能与认知发展
│   ├── McNeill_2011_*.pdf     # CER 框架与科学论证
│   └── Osborne_2004_*.pdf     # Toulmin 论证分析框架
└── 开题报告.md
```

## 快速开始

### 方式1：在线演示（无需部署）

直接访问 [GitHub Pages](https://l-i-t-t-l-e-l-i-u.github.io/weixue/)，所有演示数据已内嵌在前端中。



### 方式2：开发环境

```bash
# 后端
cd backend
pip install -r requirements.txt
编辑 .env 填入 LLM API Key
python seed.py                # 填充演示数据
uvicorn main:app --reload     # http://127.0.0.1:8000

# 前端（另开终端）
cd frontend
npm install
npm run dev                   # http://localhost:5173（自动代理到后端）
```

`.env` 配置项：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 提供商 | `dashscope` |
| `LLM_API_KEY` | API Key | — |
| `LLM_MODEL` | 模型名称 | 按提供商自动匹配 |
| `LLM_BASE_URL` | API 地址（可选） | — |

### 部署到 GitHub Pages

```bash
cd frontend
npm install -D gh-pages
npx cross-env VITE_DEMO_MODE=true VITE_BASE_PATH=/weixue/ npx vite build
npx gh-pages -d dist
```

`VITE_DEMO_MODE=true` 激活纯前端模式，API 请求全部从内嵌 JSON 返回，不需要后端。

## 参考文献

- Kuhn, D. (1999). A developmental model of critical thinking. *Educational Researcher*, 28(2), 28-46.
- Byrnes, J. P., & Dunbar, K. N. (2014). The nature and development of critical-analytic thinking. *Educational Psychology Review*, 26(4), 477-493.
- McNeill, K. L. (2011). Elementary students' views of explanation, argumentation, and evidence. *Journal of Research in Science Teaching*, 48(7), 775-803.
- Osborne, J., Erduran, S., & Simon, S. (2004). Enhancing the quality of argumentation in school science. *Journal of Research in Science Teaching*, 41(10), 994-1020.
