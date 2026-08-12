import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import useStore from '../stores/gradingStore';
import * as api from '../api/client';
import FeishuSyncCard from '../components/FeishuSyncCard';

const DIM_LABELS = {
  position: '立意（观点鲜明）', material: '选材（言之有物）',
  structure: '结构（条理清晰）', language: '语言（用词准确）',
  perspective: '视角（换位思考）',
  // 旧数据兼容：老维度 key 也统一显示为五维度
  clarity: '立意（观点鲜明）', interpretation: '立意（观点鲜明）',
  evidence_awareness: '选材（言之有物）', evidence_use: '选材（言之有物）',
  relevance: '结构（条理清晰）', inference: '结构（条理清晰）',
  argument_evaluation: '结构（条理清晰）', depth_breadth: '视角（换位思考）',
  self_regulation: '视角（换位思考）',
  清晰性: '立意（观点鲜明）', 解释力: '立意（观点鲜明）',
  证据意识: '选材（言之有物）', 证据使用: '选材（言之有物）',
  相关性: '结构（条理清晰）', 因果推理: '结构（条理清晰）',
  论证质量: '结构（条理清晰）', 深度广度: '视角（换位思考）',
  反思调节: '视角（换位思考）',
};
const TIER_LABELS = { basic: '基础层', developing: '发展层', advancing: '进阶层' };

const dimColor = (val) => {
  if (val >= 3.5) return 'text-green-600';
  if (val >= 2.5) return 'text-emerald-600';
  if (val >= 1.5) return 'text-yellow-600';
  return 'text-red-600';
};

const _legacyLocalPlan = (courseId) => {
  try {
    const raw = localStorage.getItem(`weixue-prep-plan-${courseId}`);
    if (!raw) return null;
    const saved = JSON.parse(raw);
    if (saved && (Array.isArray(saved.lessonPlan) || Array.isArray(saved.lesson_plan))) {
      return {
        lesson_plan: saved.lesson_plan || saved.lessonPlan || [],
        notes: saved.notes || {},
        confirmed: !!saved.confirmed,
      };
    }
  } catch { /* corrupted storage ignored */ }
  return null;
};

function buildPlanMarkdown({ course, analytics, insights, lessonPlan, notes, confirmed, summary }) {
  const byId = new Map(analytics.map(a => [a.topic_id, a]));
  const orderedAnalytics = [
    ...lessonPlan.map(id => byId.get(id)).filter(Boolean),
    ...analytics.filter(a => !lessonPlan.includes(a.topic_id)),
  ];
  const topicHighlights = (insights?.topic_highlights || []).reduce((m, h) => {
    (m[h.topic_id] ||= []).push(h);
    return m;
  }, {});
  const topicSummaries = (summary && summary.topics) || {};
  const lines = [];
  lines.push(`# 讲评计划 · ${course?.class_name || ''}`);
  if (course?.grade_level) lines.push(`目标年级：${course.grade_level}年级`);
  lines.push(`状态：${confirmed ? '已确认' : '草稿'}`);
  lines.push(`生成时间：${new Date().toLocaleString('zh-CN')}`);
  lines.push('');

  // 总体统计（确定性数据）
  const p = insights?.participation;
  if (p) {
    lines.push('## 总体统计');
    lines.push(`- 参评：${p.students_answered}/${p.students_total} 人，作答 ${p.responses_total} 份`);
    lines.push('- 合格线：1-3年级 ≥2.5（B+），4-6年级及以上 ≥3.0（A-），按学生各自年级判断');
    if (p.class_avg) lines.push(`- 班级均分：${p.class_avg}/4.0`);
    if (p.pass_count !== undefined) {
      lines.push(`- 达标：${p.pass_count}/${p.students_answered} 人（${Math.round((p.pass_rate || 0) * 100)}%）`);
    }
    const tier = insights.tier_summary || {};
    Object.entries(tier).forEach(([t, v]) => {
      lines.push(`- ${TIER_LABELS[t] || t}：${v.students}人，均分 ${v.avg_score}${v.weak_students ? `，低分 ${v.weak_students}人` : ''}`);
    });
    if (insights.top_tags.length) {
      lines.push(`- 高频标签：${insights.top_tags.map(t => `${t.tag}(${t.count})`).join('、')}`);
    }
    lines.push('');
  }

  // AI 总结（总体，教师可编辑）
  if (summary && (summary.overview || summary.problems || summary.suggestions)) {
    lines.push('## AI 总结（总体）');
    if (summary.overview) { lines.push(''); lines.push('### 总体情况'); lines.push(summary.overview); }
    if (summary.problems) { lines.push(''); lines.push('### 普遍/突出问题'); lines.push(summary.problems); }
    if (summary.suggestions) { lines.push(''); lines.push('### 讲评建议'); lines.push(summary.suggestions); }
    lines.push('');
  }

  // 优质发言
  if (insights?.highlights?.length) {
    lines.push('## 优质发言');
    insights.highlights.forEach(h => {
      const bonus = h.bonus_flags && h.bonus_flags.length ? `（${h.bonus_flags.join('、')}）` : '';
      lines.push(`- **${h.student_name}**《${h.topic_title}》均分 ${h.avg}${bonus}`);
      if (h.text) lines.push(`  > ${h.text}`);
    });
    lines.push('');
  }

  // 普遍/突出问题（统计）
  if (insights?.problem_patterns?.length) {
    lines.push('## 普遍/突出问题');
    insights.problem_patterns.slice(0, 5).forEach(w => {
      lines.push(`- ${w.label}：影响 ${w.students_affected} 名学生 / ${w.topics_affected} 道题`);
    });
    lines.push('');
  }

  // 分题分析
  if (analytics.length) {
    lines.push('## 分题分析');
    orderedAnalytics.forEach((row, i) => {
      lines.push('');
      lines.push(`### ${i + 1}. ${row.title}`);
      const planIdx = lessonPlan.indexOf(row.topic_id);
      if (planIdx >= 0) {
        lines.push(`- **讲评顺序：第 ${planIdx + 1} 位**`);
      }
      const dims = Object.entries(row.avg_dimension_scores || {})
        .map(([d, v]) => `${DIM_LABELS[d] || d} ${v}`)
        .join('；');
      if (dims) lines.push(`- 维度均分：${dims}`);
      if (row.weak_dimensions?.length) {
        lines.push(`- 薄弱维度：${row.weak_dimensions.map(d => DIM_LABELS[d] || d).join('、')}`);
      }
      if (row.low_students?.length) lines.push(`- 低分学生：${row.low_students.join('、')}`);
      if (row.error_tags?.length) {
        lines.push(`- 高频标签：${row.error_tags.map(t => `${t.tag}(${t.count})`).join('、')}`);
      }
      if (!dims && !row.weak_dimensions?.length && !row.low_students?.length) {
        lines.push('- 暂无评估数据，可先完成本题作答与评估');
      }
      (topicHighlights[row.topic_id] || []).forEach(h => {
        const bonus = h.bonus_flags && h.bonus_flags.length ? `（${h.bonus_flags.join('、')}）` : '';
        lines.push(`- 🏆 优质发言：${h.student_name}（均分 ${h.avg}${bonus}）`);
      });
      const ts = topicSummaries[String(row.topic_id)];
      if (ts && (ts.overview || ts.problems || ts.suggestions)) {
        if (ts.overview) lines.push(`- 本题总结：${ts.overview}`);
        if (ts.problems) lines.push(`  - 问题：${ts.problems.replace(/\n/g, ' ')}`);
        if (ts.suggestions) lines.push(`  - 建议：${ts.suggestions.replace(/\n/g, ' ')}`);
      }
      const note = notes[String(row.topic_id)] || '';
      if (note) lines.push(`- 教学备注：${note}`);
    });
    lines.push('');
  }
  return lines.join('\n');
}

function _download(filename, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function PrepPage() {
  const { courseId, course, topics, responses } = useStore();
  const [lessonPlan, setLessonPlan] = useState([]);
  const [notes, setNotes] = useState({});
  const [confirmed, setConfirmed] = useState(false);
  const [planLoaded, setPlanLoaded] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saveStatus, setSaveStatus] = useState({ kind: '', message: '' });
  const [pushStatus, setPushStatus] = useState({ kind: '', message: '' });
  const [pushing, setPushing] = useState(false);
  const [analytics, setAnalytics] = useState([]);
  const [analyticsLoading, setAnalyticsLoading] = useState(true);
  const [insights, setInsights] = useState(null);
  const [insightsLoading, setInsightsLoading] = useState(true);
  const [summary, setSummary] = useState(null);
  const [summaryGenerating, setSummaryGenerating] = useState(false);
  const [summaryStatus, setSummaryStatus] = useState({ kind: '', message: '' });
  const [topicSummaries, setTopicSummaries] = useState({});
  const [topicBusy, setTopicBusy] = useState({});
  const [topicStatus, setTopicStatus] = useState({});

  // 真实模式聚合数据来自后端 /prep（唯一口径）；demo 模式由 demoClient 本地算。
  // 用作答数据的签名监听变化（教师改分/选标签/批量评估完成都会触发），
  // 保证备课页与智能评估页、飞书卡片/多维表格始终同源。
  const analyticsVersion = useMemo(() => {
    const parts = [];
    Object.keys(responses).sort().forEach(sid => {
      (responses[sid] || []).forEach(r => {
        parts.push(
          `${r.id}:${r.teacher_reviewed ? 1 : 0}:`
          + `${JSON.stringify(r.teacher_dimension_scores || null)}:`
          + `${(r.teacher_tags || []).join(',')}`,
        );
      });
    });
    return parts.join('|');
  }, [responses]);

  // 分题分析按讲评计划顺序展示：已纳入的按顺序在前，未纳入的排在后面。
  const orderedAnalytics = useMemo(() => {
    const byId = new Map(analytics.map(a => [a.topic_id, a]));
    return [
      ...lessonPlan.map(id => byId.get(id)).filter(Boolean),
      ...analytics.filter(a => !lessonPlan.includes(a.topic_id)),
    ];
  }, [analytics, lessonPlan]);

  // 只对"当前课程"做一次默认建议：加载完成后若还没有任何计划，自动选最薄弱辩题。
  const suggestedFor = useRef(null);

  const loadAnalytics = useCallback(async () => {
    if (!courseId) return;
    setAnalyticsLoading(true);
    setInsightsLoading(true);
    let rows = [];
    let ins = null;
    try {
      [rows, ins] = await Promise.all([
        api.getPrepAnalytics(courseId),
        api.getPrepInsights(courseId),
      ]);
      rows = rows || [];
      ins = ins || null;
    } catch (e) {
      console.warn('获取备课聚合/洞察数据失败，请检查后端 /prep 接口。', e);
      rows = [];
      ins = null;
    }
    setAnalytics(rows);
    setInsights(ins);
    setAnalyticsLoading(false);
    setInsightsLoading(false);
    if (suggestedFor.current !== courseId) {
      suggestedFor.current = courseId;
      setLessonPlan(prev => {
        if (prev.length > 0) return prev;
        const weak = rows.filter(d => d.weak_dimensions.length > 0);
        const suggested = weak.length > 0 ? weak : rows;
        return suggested.slice(0, 3).map(d => d.topic_id);
      });
      setDirty(false);
    }
  }, [courseId]);

  useEffect(() => {
    loadAnalytics();
  }, [courseId, analyticsVersion, loadAnalytics]);

  const loadPlan = useCallback(async () => {
    if (!courseId) return;
    setPlanLoaded(false);
    const validIds = new Set(topics.map(t => t.id));
    let lp = [];
    let nt = {};
    let cf = false;
    let sm = null;
    let migratedLegacy = false;
    try {
      const plan = await api.getPrepPlan(courseId);
      lp = (plan.lesson_plan || []).filter(id => validIds.has(id));
      nt = plan.notes || {};
      cf = !!plan.confirmed;
      sm = plan.summary || null;
      // 真实后端还没有计划时，把本机旧 localStorage 计划迁移上来（保存后即入系统）
      if (lp.length === 0) {
        const legacy = _legacyLocalPlan(courseId);
        if (legacy) {
          lp = (legacy.lesson_plan || []).filter(id => validIds.has(id));
          nt = legacy.notes || {};
          cf = !!legacy.confirmed;
          migratedLegacy = true;
        }
      }
    } catch (e) {
      console.warn('加载讲评计划失败，回退本机缓存。', e);
      const legacy = _legacyLocalPlan(courseId);
      if (legacy) {
        lp = (legacy.lesson_plan || []).filter(id => validIds.has(id));
        nt = legacy.notes || {};
        cf = !!legacy.confirmed;
        migratedLegacy = true;
      }
    }
    // 已保存计划优先；否则保留当前状态（可能是刚加载出的默认建议），不覆盖。
    setLessonPlan(prev => {
      if (lp.length > 0) return lp;
      if (migratedLegacy) return lp;
      return prev;
    });
    setNotes(nt);
    setConfirmed(cf);
    setSummary(sm);
    setTopicSummaries((sm && sm.topics) || {});
    setDirty(false);
    setPlanLoaded(true);
  }, [courseId, topics]);

  useEffect(() => {
    if (courseId) loadPlan();
  }, [courseId, loadPlan]);

  const markDirty = () => setDirty(true);

  const moveItem = (idx, dir) => {
    const ni = idx + dir;
    if (ni < 0 || ni >= lessonPlan.length) return;
    const nl = [...lessonPlan];
    [nl[idx], nl[ni]] = [nl[ni], nl[idx]];
    setLessonPlan(nl);
    markDirty();
  };

  const removeFromPlan = (topicId) => {
    setLessonPlan(lessonPlan.filter(item => item !== topicId));
    markDirty();
  };

  const addToPlan = (topicId) => {
    if (lessonPlan.includes(topicId)) return;
    setLessonPlan([...lessonPlan, topicId]);
    markDirty();
  };

  const updateNote = (topicId, value) => {
    setNotes({ ...notes, [String(topicId)]: value });
    markDirty();
  };

  const persist = async (withConfirm) => {
    if (!courseId || lessonPlan.length === 0) {
      setSaveStatus({ kind: 'error', message: '请先至少加入一个辩题再保存。' });
      return;
    }
    const nextConfirmed = withConfirm ? true : confirmed;
    setSaveStatus({ kind: 'saving', message: withConfirm ? '正在确认并保存讲评计划...' : '正在保存草稿...' });
    try {
      const saved = await api.savePrepPlan(courseId, {
        lesson_plan: lessonPlan,
        notes,
        confirmed: nextConfirmed,
      });
      setConfirmed(!!saved.confirmed);
      setDirty(false);
      setSaveStatus({
        kind: withConfirm ? 'confirmed' : 'saved',
        message: withConfirm
          ? '讲评计划已确认并保存到系统，任何设备打开都能看到。'
          : '草稿已保存到系统。',
      });
    } catch (e) {
      setSaveStatus({
        kind: 'error',
        message: `保存失败：${e?.response?.data?.detail || e?.message || '未知错误'}`,
      });
    }
  };

  const copyMarkdown = async () => {
    const md = buildPlanMarkdown({ course, analytics, insights, lessonPlan, notes, confirmed, summary });
    try {
      await navigator.clipboard.writeText(md);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = md;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    setSaveStatus({ kind: 'exported', message: '讲评计划 Markdown 已复制到剪贴板。' });
  };

  const downloadMarkdown = () => {
    const md = buildPlanMarkdown({ course, analytics, insights, lessonPlan, notes, confirmed, summary });
    _download(`讲评计划-${course?.class_name || courseId}.md`, new Blob([md], { type: 'text/markdown;charset=utf-8' }));
    setSaveStatus({ kind: 'exported', message: 'Markdown 文件已下载。' });
  };

  const downloadJson = () => {
    const payload = {
      course_id: courseId,
      course_name: course?.class_name || '',
      lesson_plan: lessonPlan,
      notes,
      confirmed,
      summary: summary || {},
      insights: {
        participation: insights?.participation || {},
        tier_summary: insights?.tier_summary || {},
        highlights: insights?.highlights || [],
        topic_highlights: insights?.topic_highlights || [],
        problem_patterns: insights?.problem_patterns || [],
        top_tags: insights?.top_tags || [],
      },
      saved_at: new Date().toISOString(),
    };
    _download(
      `讲评计划-${course?.class_name || courseId}.json`,
      new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' }),
    );
    setSaveStatus({ kind: 'exported', message: 'JSON 文件已下载。' });
  };

  const pushCard = async () => {
    if (!courseId || lessonPlan.length === 0) return;
    setPushing(true);
    setPushStatus({ kind: '', message: '' });
    try {
      // 推送前先落库当前状态（含最新备注/顺序），保证卡片内容与网页一致。
      const saved = await api.savePrepPlan(courseId, {
        lesson_plan: lessonPlan,
        notes,
        confirmed,
      });
      setConfirmed(!!saved.confirmed);
      setDirty(false);
      const r = await api.pushPrepPlanCard(courseId);
      setPushStatus({
        kind: r.ok ? (r.status === 'delivered' ? 'ok' : 'warn') : 'error',
        message: r.message,
      });
    } catch (e) {
      setPushStatus({
        kind: 'error',
        message: `推送失败：${e?.response?.data?.detail || e?.message || '未知错误'}`,
      });
    }
    setPushing(false);
  };

  const generateSummary = async () => {
    if (!courseId || summaryGenerating) return;
    setSummaryGenerating(true);
    setSummaryStatus({ kind: '', message: '' });
    try {
      const result = await api.generatePrepSummary(courseId);
      setSummary(result || null);
      setTopicSummaries((result && result.topics) || {});
      setSummaryStatus({
        kind: 'ok',
        message: result?.generated_by === 'llm'
          ? 'AI 总结已生成并保存（可在导出/飞书卡片中复用）。'
          : '已生成数据总结（未配置 LLM，使用规则模板；配置 LLM_API_KEY 后可获得 AI 版）。',
      });
    } catch (e) {
      setSummaryStatus({
        kind: 'error',
        message: `生成失败：${e?.response?.data?.detail || e?.message || '未知错误'}`,
      });
    }
    setSummaryGenerating(false);
  };

  const saveSummary = async () => {
    if (!courseId || !summary) return;
    setSummaryStatus({ kind: '', message: '' });
    try {
      const saved = await api.savePrepSummary(courseId, {
        overview: summary.overview,
        problems: summary.problems,
        suggestions: summary.suggestions,
      });
      setSummary(saved);
      setTopicSummaries((saved && saved.topics) || {});
      setSummaryStatus({ kind: 'ok', message: '总体总结已保存。' });
    } catch (e) {
      setSummaryStatus({
        kind: 'error',
        message: `保存失败：${e?.response?.data?.detail || e?.message || '未知错误'}`,
      });
    }
  };

  const updateSummary = (key, value) => {
    if (!summary) return;
    setSummary({ ...summary, [key]: value });
  };

  const generateTopicSummary = async (topicId) => {
    if (!courseId || topicBusy[topicId]) return;
    setTopicBusy(b => ({ ...b, [topicId]: true }));
    setTopicStatus(s => ({ ...s, [topicId]: { kind: '', message: '' } }));
    try {
      const result = await api.generateTopicSummary(courseId, topicId);
      setTopicSummaries(prev => ({ ...prev, [String(topicId)]: result || {} }));
      setTopicStatus(s => ({
        ...s,
        [topicId]: {
          kind: 'ok',
          message: result?.generated_by === 'llm' ? '本题 AI 总结已生成，可编辑。' : '已生成数据总结（模板），可编辑。',
        },
      }));
    } catch (e) {
      setTopicStatus(s => ({
        ...s,
        [topicId]: {
          kind: 'error',
          message: `生成失败：${e?.response?.data?.detail || e?.message || '未知错误'}`,
        },
      }));
    }
    setTopicBusy(b => ({ ...b, [topicId]: false }));
  };

  const saveTopicSummary = async (topicId) => {
    const ts = topicSummaries[String(topicId)];
    if (!courseId || !ts) return;
    setTopicStatus(s => ({ ...s, [topicId]: { kind: '', message: '' } }));
    try {
      const saved = await api.savePrepSummary(courseId, {
        topic_id: topicId,
        overview: ts.overview,
        problems: ts.problems,
        suggestions: ts.suggestions,
      });
      setTopicSummaries(prev => ({
        ...prev,
        [String(topicId)]: (saved && saved.topics && saved.topics[String(topicId)]) || ts,
      }));
      setTopicStatus(s => ({ ...s, [topicId]: { kind: 'ok', message: '本题总结已保存。' } }));
    } catch (e) {
      setTopicStatus(s => ({
        ...s,
        [topicId]: {
          kind: 'error',
          message: `保存失败：${e?.response?.data?.detail || e?.message || '未知错误'}`,
        },
      }));
    }
  };

  const updateTopicSummary = (topicId, key, value) => {
    const ts = topicSummaries[String(topicId)];
    if (!ts) return;
    setTopicSummaries(prev => ({
      ...prev,
      [String(topicId)]: { ...prev[String(topicId)], [key]: value },
    }));
  };

  if (!courseId) {
    return <div className="text-slate-400 py-10 text-center">暂无课程数据。</div>;
  }
  if (analyticsLoading && analytics.length === 0) {
    return <div className="text-slate-400 py-10 text-center">正在加载备课数据...</div>;
  }
  if (analytics.length === 0) {
    return <div className="text-slate-400 py-10 text-center">暂无评估数据，请先在课堂模式或智能评估中完成评估。</div>;
  }

  if (!planLoaded) {
    return <div className="text-slate-400 py-10 text-center">正在加载讲评计划...</div>;
  }

  const statusCls = {
    confirmed: 'text-green-700',
    saved: 'text-green-700',
    exported: 'text-indigo-600',
    error: 'text-red-600',
    saving: 'text-slate-500',
  }[saveStatus.kind] || 'text-slate-500';

  return (
    <div className="flex flex-col gap-4">
      {/* Top banner + actions */}
      <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-xl p-3.5 border border-blue-200 flex gap-2.5 items-start">
        <span className="text-lg">🤖</span>
        <div className="flex-1 text-sm text-blue-800">
          基于全班多维度评估结果，已为您整理讲评建议。请根据您的教学判断调整，确认后计划会保存到系统，并可导出、同步飞书多维表格或推送机器人卡片。
        </div>
        {confirmed && !dirty && (
          <span className="shrink-0 text-[11px] bg-green-100 text-green-700 border border-green-200 px-2 py-0.5 rounded-full">
            已确认 ✓
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => persist(false)}
          disabled={lessonPlan.length === 0 || saveStatus.kind === 'saving'}
          className="px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-600 cursor-pointer hover:bg-slate-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          保存草稿
        </button>
        <button
          onClick={() => persist(true)}
          disabled={lessonPlan.length === 0 || saveStatus.kind === 'saving'}
          className="px-4 py-1.5 text-xs font-medium rounded-lg bg-indigo-600 text-white cursor-pointer hover:bg-indigo-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {confirmed && !dirty ? '讲评计划已确认 ✓' : dirty && confirmed ? '重新确认讲评计划 →' : '确认讲评计划 →'}
        </button>
        <div className="flex-1" />
        <button
          onClick={copyMarkdown}
          disabled={lessonPlan.length === 0}
          className="px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-600 cursor-pointer hover:bg-slate-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          ⧉ 复制 Markdown
        </button>
        <button
          onClick={downloadMarkdown}
          disabled={lessonPlan.length === 0}
          className="px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-600 cursor-pointer hover:bg-slate-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          ⬇ 下载 .md
        </button>
        <button
          onClick={downloadJson}
          disabled={lessonPlan.length === 0}
          className="px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-600 cursor-pointer hover:bg-slate-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          ⬇ 下载 .json
        </button>
      </div>

      {saveStatus.message && (
        <div className={`text-xs ${statusCls}`}>{saveStatus.message}</div>
      )}

      {/* ── 总体情况（确定性统计） ─────────────────────── */}
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-lg">📊</span>
          <h3 className="text-sm font-semibold text-slate-800">总体情况</h3>
          <span className="text-[11px] bg-blue-50 text-blue-700 border border-blue-200 px-1.5 py-0.5 rounded">自动统计</span>
        </div>
        {insightsLoading && !insights ? (
          <div className="text-xs text-slate-400 py-3">正在统计参与与表现...</div>
        ) : insights ? (
          <>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-3">
              {[
                { label: '参评人数', value: `${insights.participation.students_answered}/${insights.participation.students_total} 人` },
                { label: '作答份数', value: `${insights.participation.responses_total} 份` },
                { label: '辩题数', value: `${insights.participation.per_topic.length} 道` },
                {
                  label: '达标人数',
                  value: `${insights.participation.pass_count ?? 0}人 · ${Math.round((insights.participation.pass_rate ?? 0) * 100)}%`,
                },
                { label: '班级均分', value: insights.participation.class_avg ? `${insights.participation.class_avg.toFixed(1)}/4.0` : '未评' },
              ].map(s => (
                <div key={s.label} className="bg-slate-50 rounded-lg px-3 py-2 border border-slate-100">
                  <div className="text-[11px] text-slate-400">{s.label}</div>
                  <div className="text-base font-bold text-slate-800 mt-0.5">{s.value}</div>
                </div>
              ))}
            </div>
            {Object.keys(insights.tier_summary || {}).length > 0 && (
              <div className="flex gap-1.5 flex-wrap mb-2">
                {Object.entries(insights.tier_summary).map(([tier, t]) => (
                  <span key={tier} className="text-[11px] bg-indigo-50 text-indigo-700 border border-indigo-200 px-2 py-0.5 rounded">
                    {TIER_LABELS[tier] || tier} · {t.students}人 · 均分{t.avg_score}
                  </span>
                ))}
              </div>
            )}
            <div className="text-[11px] text-slate-400 mb-2">
              合格线：1-3年级 ≥2.5（B+），4-6年级及以上 ≥3.0（A-），按学生各自年级判断
            </div>
            {insights.top_tags.length > 0 && (
              <div className="flex gap-1 flex-wrap items-center">
                <span className="text-[11px] text-slate-400">高频标签：</span>
                {insights.top_tags.map(t => (
                  <span key={t.tag} className="text-[11px] bg-orange-50 text-orange-700 border border-orange-200 px-1.5 py-0.5 rounded">
                    {t.tag} ({t.count})
                  </span>
                ))}
              </div>
            )}
          </>
        ) : null}
      </div>

      {/* ── AI 总结（LLM 生成，按钮触发，模板兜底） ─────── */}
      <div className="bg-gradient-to-r from-indigo-50 to-violet-50 rounded-xl border border-indigo-200 p-4">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-lg">🤖</span>
          <h3 className="text-sm font-semibold text-slate-800">AI 总结</h3>
          {summary && (
            <span className={`text-[11px] px-1.5 py-0.5 rounded border ${
              summary.generated_by === 'llm'
                ? 'bg-green-100 text-green-700 border-green-200'
                : 'bg-amber-100 text-amber-700 border-amber-200'
            }`}>
              {summary.generated_by === 'llm' ? 'AI 生成' : '模板生成'}
            </span>
          )}
          <button
            onClick={generateSummary}
            disabled={summaryGenerating}
            className="ml-auto text-[11px] px-2.5 py-1 rounded-md border border-indigo-300 bg-white text-indigo-700 font-medium transition-colors cursor-pointer hover:bg-indigo-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {summaryGenerating ? '生成中...' : summary ? '重新生成' : '生成 AI 总结'}
          </button>
        </div>
        {summaryStatus.message && (
          <div className={`mb-2 text-xs ${summaryStatus.kind === 'error' ? 'text-red-600' : 'text-indigo-700'}`}>
            {summaryStatus.message}
          </div>
        )}
        {summary ? (
          <>
            {[
              { key: 'overview', label: '总体情况', icon: '📋' },
              { key: 'problems', label: '普遍/突出问题', icon: '⚠️' },
              { key: 'suggestions', label: '讲评建议', icon: '💡' },
            ].map(b => (
              <div key={b.key} className="mb-2.5 last:mb-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-slate-600">{b.icon} {b.label}</span>
                  {summary.edited && (
                    <span className="text-[10px] text-indigo-500">（已编辑）</span>
                  )}
                </div>
                <textarea
                  value={summary[b.key] || ''}
                  onChange={e => updateSummary(b.key, e.target.value)}
                  placeholder={`AI 生成后这里会自动填充，可直接修改为您的讲评口径。`}
                  className="w-full text-xs border border-slate-200 rounded-md px-2.5 py-1.5 resize-y min-h-[52px] outline-none focus:ring-1 focus:ring-indigo-300"
                />
              </div>
            ))}
            <div className="flex items-center gap-2">
              <button
                onClick={saveSummary}
                className="text-[11px] px-2.5 py-1 rounded-md border border-indigo-300 bg-white text-indigo-700 font-medium transition-colors cursor-pointer hover:bg-indigo-50"
              >
                保存总体总结
              </button>
              {summary.generated_at && (
                <span className="text-[10px] text-slate-400">
                  生成于 {new Date(summary.generated_at).toLocaleString('zh-CN')}
                </span>
              )}
            </div>
          </>
        ) : (
          <div className="text-xs text-slate-500">
            点击右上角按钮，AI 将基于班级数据生成总体情况、普遍/突出问题与讲评建议；
            未配置 LLM 时自动使用规则模板，不会中断备课。
          </div>
        )}
      </div>

      {/* ── 分题分析（每题独立） ───────────────────────── */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">🧩</span>
          <h3 className="text-sm font-semibold text-slate-800">分题分析</h3>
          <span className="text-[11px] bg-blue-50 text-blue-700 border border-blue-200 px-1.5 py-0.5 rounded">
            在每题卡片中决定是否纳入讲评与顺序；点「生成本题总结」才调用 AI
          </span>
        </div>
        {insightsLoading && !insights ? (
          <div className="text-xs text-slate-400 py-3">正在统计各题表现...</div>
        ) : analytics.length === 0 ? (
          <div className="text-xs text-slate-400 py-3">暂无辩题数据。</div>
        ) : (
          orderedAnalytics.map(row => {
            const tid = row.topic_id;
            const ts = topicSummaries[String(tid)];
            const planIdx = lessonPlan.indexOf(tid);
            const inPlan = planIdx >= 0;
            const perTopic = (insights?.participation?.per_topic || [])
              .find(pt => pt.topic_id === tid);
            const hl = (insights?.topic_highlights || [])
              .filter(h => h.topic_id === tid)
              .slice(0, 2);
            const status = topicStatus[tid] || {};
            return (
              <div key={tid} className={`bg-white rounded-xl border p-4 ${inPlan ? 'border-blue-200' : 'border-slate-200'}`}>
                <div className="flex items-start gap-3">
                  <div className="flex flex-col items-center gap-0.5 shrink-0 pt-1">
                    <span className={`w-6 h-6 rounded-md text-xs font-bold flex items-center justify-center ${
                      inPlan ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-400'
                    }`}>
                      {inPlan ? planIdx + 1 : '·'}
                    </span>
                    <button onClick={() => moveItem(planIdx, -1)} disabled={!inPlan || planIdx === 0}
                      className="text-slate-300 hover:text-slate-500 text-[11px] disabled:opacity-30 cursor-pointer">▲</button>
                    <button onClick={() => moveItem(planIdx, 1)} disabled={!inPlan || planIdx === lessonPlan.length - 1}
                      className="text-slate-300 hover:text-slate-500 text-[11px] disabled:opacity-30 cursor-pointer">▼</button>
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-sm font-semibold text-slate-800">{row.title}</span>
                      <span className="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded">{row.topic_type}</span>
                    </div>
                    <div className="text-[11px] text-slate-400 mb-2">
                      作答 {perTopic?.responses ?? 0} 份 · 已审 {perTopic?.reviewed ?? 0} 份
                      {perTopic?.passing > 0 && (
                        <span className="ml-2 text-emerald-600 font-medium">达标 {perTopic.passing} 份</span>
                      )}
                    </div>
                    <div className="flex gap-1.5 flex-wrap mb-2">
                      {Object.entries(row.avg_dimension_scores || {}).map(([dim, val]) => (
                        <span key={dim} className={`text-[11px] font-medium ${dimColor(val)}`}>
                          {DIM_LABELS[dim] || dim} {val.toFixed(1)}
                        </span>
                      ))}
                    </div>
                    <div className="flex gap-1 flex-wrap mb-1">
                      {row.weak_dimensions.map(dim => (
                        <span key={dim} className="text-[11px] bg-red-50 text-red-700 border border-red-200 px-1.5 py-0.5 rounded">
                          薄弱: {DIM_LABELS[dim] || dim}
                        </span>
                      ))}
                      {row.low_students.length > 0 && (
                        <span className="text-[11px] text-slate-500">低分：{row.low_students.join('、')}</span>
                      )}
                    </div>
                    {row.error_tags.length > 0 && (
                      <div className="flex gap-1 flex-wrap mb-1">
                        {row.error_tags.slice(0, 4).map(et => (
                          <span key={et.tag} className="text-[11px] bg-orange-50 text-orange-700 border border-orange-200 px-1.5 py-0.5 rounded">
                            {et.tag} ({et.count})
                          </span>
                        ))}
                      </div>
                    )}
                    <textarea placeholder="添加讲解备注（讲评顺序导出/卡片中会带上）..." value={notes[String(tid)] || ''}
                      onChange={e => updateNote(tid, e.target.value)}
                      className="w-full text-xs border border-slate-200 rounded-md px-2.5 py-1.5 resize-none min-h-[32px] outline-none focus:ring-1 focus:ring-indigo-300" />
                  </div>
                  <div className="flex flex-col items-end gap-2 shrink-0">
                    <button
                      onClick={() => inPlan ? removeFromPlan(tid) : addToPlan(tid)}
                      className={`shrink-0 text-[11px] px-2.5 py-1 rounded-md border font-medium transition-colors cursor-pointer ${
                        inPlan
                          ? 'border-blue-300 bg-blue-50 text-blue-700 hover:bg-blue-100'
                          : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50'
                      }`}
                    >
                      {inPlan ? '已纳入讲评 ✓' : '纳入讲评'}
                    </button>
                    <button
                      onClick={() => generateTopicSummary(tid)}
                      disabled={topicBusy[tid]}
                      className="shrink-0 text-[11px] px-2.5 py-1 rounded-md border border-indigo-300 bg-white text-indigo-700 font-medium transition-colors cursor-pointer hover:bg-indigo-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      {topicBusy[tid] ? '生成中...' : ts ? '重新生成' : '生成本题总结'}
                    </button>
                  </div>
                </div>

                {hl.length > 0 && (
                  <div className="flex gap-2 flex-wrap mt-2">
                    {hl.map(h => (
                      <span key={`${h.student_id}`} className="text-[11px] bg-amber-50 text-amber-800 border border-amber-200 px-2 py-1 rounded">
                        🏆 {h.student_name}（{h.avg.toFixed(1)}）{h.bonus_flags && h.bonus_flags.length ? `✨${h.bonus_flags.join('、')}` : ''}
                      </span>
                    ))}
                  </div>
                )}

                {ts && (ts.overview || ts.problems || ts.suggestions) ? (
                  <div className="mt-3 border-t border-slate-100 pt-3">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-xs font-medium text-slate-600">🤖 本题总结</span>
                      {ts.edited && <span className="text-[10px] text-indigo-500">（已编辑）</span>}
                      {ts.generated_by && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
                          ts.generated_by === 'llm' ? 'bg-green-100 text-green-700 border-green-200' : 'bg-amber-100 text-amber-700 border-amber-200'
                        }`}>
                          {ts.generated_by === 'llm' ? 'AI 生成' : '模板生成'}
                        </span>
                      )}
                      <div className="ml-auto">
                        <button
                          onClick={() => saveTopicSummary(tid)}
                          className="text-[11px] px-2.5 py-1 rounded-md border border-indigo-300 bg-white text-indigo-700 font-medium transition-colors cursor-pointer hover:bg-indigo-50"
                        >
                          保存本题总结
                        </button>
                      </div>
                    </div>
                    {[
                      { key: 'overview', label: '总体情况' },
                      { key: 'problems', label: '普遍/突出问题' },
                      { key: 'suggestions', label: '讲评建议' },
                    ].map(b => (
                      <div key={b.key} className="mb-2">
                        <div className="text-[11px] font-medium text-slate-500 mb-0.5">{b.label}</div>
                        <textarea
                          value={ts[b.key] || ''}
                          onChange={e => updateTopicSummary(tid, b.key, e.target.value)}
                          className="w-full text-xs border border-slate-200 rounded-md px-2.5 py-1.5 resize-y min-h-[40px] outline-none focus:ring-1 focus:ring-indigo-300"
                        />
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-3 border-t border-slate-100 pt-2 text-[11px] text-slate-400">
                    点击右上角按钮生成此题总结（不点不生成）。
                  </div>
                )}
                {status.message && (
                  <div className={`mt-2 text-[11px] ${status.kind === 'error' ? 'text-red-600' : 'text-indigo-700'}`}>
                    {status.message}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* ── 优质发言（闪光点） ─────────────────────────── */}
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-lg">🏆</span>
          <h3 className="text-sm font-semibold text-slate-800">优质发言</h3>
          <span className="text-[11px] bg-amber-50 text-amber-700 border border-amber-200 px-1.5 py-0.5 rounded">讲评时可展示</span>
        </div>
        {insightsLoading && !insights ? (
          <div className="text-xs text-slate-400 py-2">正在挑选优秀示例...</div>
        ) : insights && insights.highlights.length > 0 ? (
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
            {insights.highlights.map((h, i) => (
              <div key={`${h.student_id}-${h.topic_id}`} className="bg-gradient-to-br from-amber-50 to-orange-50 rounded-xl p-3 border border-amber-200">
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="text-xs">🏆</span>
                  <span className="text-sm font-semibold text-slate-800">{h.student_name}</span>
                  <span className="text-[10px] bg-white border border-amber-200 text-amber-700 px-1.5 rounded">{h.grade}年级</span>
                  <span className="ml-auto text-[11px] font-bold text-amber-700">{h.avg.toFixed(1)}</span>
                </div>
                <div className="text-[11px] text-slate-500 mb-1.5">《{h.topic_title}》</div>
                <p className="text-xs text-slate-600 leading-relaxed mb-2 line-clamp-2">“{h.text}”</p>
                <div className="flex gap-1 flex-wrap">
                  {Object.entries(h.scores).slice(0, 5).map(([d, r]) => (
                    <span key={d} className="text-[10px] bg-white border border-amber-200 text-slate-600 px-1.5 py-0.5 rounded">
                      {DIM_LABELS[d] || d} {r}
                    </span>
                  ))}
                  {(h.bonus_flags || []).map(f => (
                    <span key={f} className="text-[10px] bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded">✨{f}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-slate-400 py-2">暂无高分发言（均分 3.0 以上），评估完成后自动出现。</div>
        )}
      </div>

      {/* ── 普遍/突出问题（数据统计） ───────────────────── */}
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-lg">⚠️</span>
          <h3 className="text-sm font-semibold text-slate-800">普遍/突出问题</h3>
          <span className="text-[11px] bg-red-50 text-red-700 border border-red-200 px-1.5 py-0.5 rounded">低于合格线的维度</span>
        </div>
        {insightsLoading && !insights ? (
          <div className="text-xs text-slate-400 py-2">正在统计薄弱维度...</div>
        ) : insights && insights.problem_patterns.length > 0 ? (
          <div>
            {insights.problem_patterns.slice(0, 5).map(p => {
              const total = insights.participation.students_answered || 1;
              return (
                <div key={p.dimension} className="flex items-center gap-3 py-2 border-b border-slate-100 last:border-0">
                  <span className="w-24 shrink-0 text-xs font-medium text-slate-700">{p.label}</span>
                  <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-red-400 rounded-full"
                      style={{ width: `${Math.min(100, Math.round(p.students_affected / total * 100))}%` }}
                    />
                  </div>
                  <span className="shrink-0 text-[11px] text-slate-500">{p.students_affected}人 · {p.topics_affected}题</span>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-xs text-slate-400 py-2">当前未发现低于合格线的维度，可在讲评中进入拓展追问。</div>
        )}
      </div>

      {/* Feishu delivery: Bitable sync + bot card push */}
      <div className="flex flex-col gap-2">
        <FeishuSyncCard courseId={courseId} />
        <div className="bg-white rounded-xl border border-slate-200 p-3.5">
          <div className="flex items-center gap-2.5">
            <span className="w-2 h-2 rounded-full bg-indigo-400" />
            <span className="text-xs font-medium text-slate-700">飞书机器人 · 讲评计划卡片</span>
            <button
              onClick={pushCard}
              disabled={pushing || lessonPlan.length === 0}
              className="ml-auto text-[11px] px-2.5 py-1 rounded-md border border-indigo-300 bg-white text-indigo-700 font-medium transition-colors cursor-pointer hover:bg-indigo-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {pushing ? '推送中...' : '推送卡片'}
            </button>
          </div>
          {pushStatus.message && (
            <div className={`mt-2 text-xs ${pushStatus.kind === 'ok' ? 'text-green-700' : pushStatus.kind === 'warn' ? 'text-amber-700' : pushStatus.kind === 'error' ? 'text-red-600' : 'text-slate-500'}`}>
              {pushStatus.message}
            </div>
          )}
          {!pushStatus.message && (
            <div className="mt-2 text-[11px] text-slate-400">
              计划确认后一键推送到飞书机器人，卡片内可再次确认或跳回网页调整（需配置 FEISHU_TEACHER_OPEN_ID）。
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
