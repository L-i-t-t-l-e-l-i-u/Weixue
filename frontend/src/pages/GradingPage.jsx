import { useState, useEffect } from 'react';
import useStore from '../stores/gradingStore';
import * as api from '../api/client';

/* ── Rating color helper ─────────────────────────────────── */
const ratingColor = (rating) => {
  const map = {
    'A+': { bg: 'bg-green-100',   text: 'text-green-700',   border: 'border-green-300' },
    'A':  { bg: 'bg-emerald-50',  text: 'text-emerald-700', border: 'border-emerald-200' },
    'A-': { bg: 'bg-blue-50',     text: 'text-blue-700',    border: 'border-blue-200' },
    'B+': { bg: 'bg-amber-50',    text: 'text-amber-700',   border: 'border-amber-200' },
    'B':  { bg: 'bg-yellow-50',   text: 'text-yellow-700',  border: 'border-yellow-200' },
    'B-': { bg: 'bg-red-100',     text: 'text-red-700',     border: 'border-red-200' },
  };
  return map[rating] || { bg: 'bg-slate-100', text: 'text-slate-500', border: 'border-slate-300' };
};

const DIM_LABELS = {
  clarity: '清晰性', interpretation: '解释力', evidence_awareness: '证据意识',
  relevance: '相关性', inference: '因果推理', evidence_use: '证据使用',
  argument_evaluation: '论证质量', depth_breadth: '深度广度', self_regulation: '反思调节',
};

/* Compute an overall "average" rating number from dimension scores dict */
const ratingToNum = { 'A+': 4, 'A': 3.5, 'A-': 3, 'B+': 2.5, 'B': 2, 'B-': 1 };
const avgRating = (scores) => {
  if (!scores) return 0;
  const vals = Object.values(scores).map(r => ratingToNum[r] || 0);
  return vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
};

const overallBadge = (avg) => {
  if (avg >= 3.5) return { label: '优秀', cls: 'bg-green-100 text-green-700' };
  if (avg >= 2.5) return { label: '良好', cls: 'bg-emerald-50 text-emerald-700' };
  if (avg >= 1.5) return { label: '待提升', cls: 'bg-yellow-50 text-yellow-700' };
  if (avg > 0)    return { label: '薄弱', cls: 'bg-red-100 text-red-700' };
  return { label: '未评', cls: 'bg-slate-100 text-slate-500' };
};

export default function GradingPage() {
  const { students, topics, responses, currentStudentIdx, setStudentIdx, submitReview, courseId, tags, refreshTags } = useStore();
  const [expandedTopic, setExpandedTopic] = useState(null);
  const [calibrations, setCalibrations] = useState({ total: 0, records: [] });
  const [showCalibrations, setShowCalibrations] = useState(false);

  useEffect(() => {
    if (courseId) {
      api.getCalibrations(courseId, 10).then(setCalibrations).catch(() => {});
    }
  }, [courseId]);

  const student = students[currentStudentIdx];
  if (!student) return <div className="text-slate-400 py-10 text-center">暂无学生数据</div>;

  const resps = responses[student.id] || [];
  const respMap = {};
  resps.forEach(r => { respMap[r.topic_id] = r; });

  // Student overall stats (only count topics with actual responses)
  let totalAvg = 0, topicCount = 0;
  topics.forEach(t => {
    const r = respMap[t.id];
    if (!r || !r.raw_text || !r.raw_text.trim()) return;
    const scores = r.teacher_dimension_scores || r.ai_dimension_scores;
    if (scores) { totalAvg += avgRating(scores); topicCount++; }
  });
  const studentAvg = topicCount > 0 ? totalAvg / topicCount : 0;
  const badge = overallBadge(studentAvg);

  // Only show topics the student actually answered
  const studentTopics = topics.filter(t => {
    const r = respMap[t.id];
    return r && r.raw_text && r.raw_text.trim();
  });

  return (
    <div className="grid grid-cols-[220px_1fr] gap-5">
      {/* ── Student List ──────────────────────────────── */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100 text-sm font-semibold text-slate-600">学生列表</div>
        {students.map((st, i) => {
          const ss = responses[st.id] || [];
          const sm = {};
          ss.forEach(r => { sm[r.topic_id] = r; });
          let avg = 0, cnt = 0;
          topics.forEach(t => {
            const r = sm[t.id];
            if (!r || !r.raw_text || !r.raw_text.trim()) return;
            const sc = r.teacher_dimension_scores || r.ai_dimension_scores;
            if (sc) { avg += avgRating(sc); cnt++; }
          });
          const stAvg = cnt > 0 ? avg / cnt : 0;
          const stBadge = overallBadge(stAvg);
          const active = i === currentStudentIdx;
          return (
            <div
              key={st.id}
              onClick={() => { setStudentIdx(i); setExpandedTopic(null); }}
              className={`px-4 py-2.5 cursor-pointer border-b border-slate-50 flex justify-between items-center transition-colors
                ${active ? 'bg-indigo-50 border-l-[3px] border-l-indigo-600' : 'border-l-[3px] border-l-transparent hover:bg-slate-50'}`}
            >
              <div>
                <span className={`text-sm ${active ? 'font-semibold text-indigo-900' : 'text-slate-600'}`}>{st.name}</span>
                <span className="text-[10px] text-slate-400 ml-1.5">{st.grade}年级</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${stBadge.cls}`}>{stBadge.label}</span>
              </div>
            </div>
          );
        })}
        <div className="px-4 py-3 bg-slate-50 border-t border-slate-200">
          <div className="text-[11px] text-slate-500 mb-1">全班统计（{students.length}人）</div>
        </div>
      </div>

      {/* ── Grading Area ──────────────────────────────── */}
      <div className="flex flex-col gap-4">
        {/* Student header */}
        <div className="bg-white rounded-xl p-4 border border-slate-200 flex justify-between items-center">
          <div>
            <div className="text-base font-semibold text-slate-900">{student.name}</div>
            <div className="text-xs text-slate-400 mt-0.5">
              {student.grade}年级 · {studentTopics.length}个辩题
              {student.cognitive_tier && <span className="ml-2 text-indigo-500">{({basic:'基础层',developing:'发展层',advancing:'进阶层'})[student.cognitive_tier]}</span>}
            </div>
          </div>
          <div className="text-right">
            <span className={`text-sm font-semibold px-3 py-1 rounded-lg ${badge.cls}`}>{badge.label}</span>
          </div>
        </div>

        {/* Teacher Calibration Memory Panel */}
        {calibrations.total > 0 && (
          <div className="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl border border-indigo-200 overflow-hidden">
            <div
              onClick={() => setShowCalibrations(!showCalibrations)}
              className="px-4 py-3 cursor-pointer flex items-center gap-3 hover:from-indigo-100 hover:to-purple-100 transition-colors"
            >
              <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white text-sm">🧠</div>
              <div className="flex-1">
                <div className="text-sm font-semibold text-indigo-900">教师校准记忆</div>
                <div className="text-xs text-indigo-600">AI已学习您的 {calibrations.total} 条批改记录，评估时自动参考</div>
              </div>
              <span className={`text-indigo-400 transition-transform ${showCalibrations ? 'rotate-180' : ''}`}>▾</span>
            </div>
            {showCalibrations && (
              <div className="px-4 pb-4 border-t border-indigo-200">
                <div className="mt-3 space-y-2">
                  {calibrations.records.map((rec, i) => (
                    <div key={rec.id} className="bg-white/80 rounded-lg p-3 border border-indigo-100">
                      <div className="text-xs text-slate-500 mb-1">校准记录 {i + 1}</div>
                      <div className="text-sm space-y-1">
                        <div>
                          <span className="text-slate-500">AI评分：</span>
                          <span className="text-slate-700">{rec.ai_scores}</span>
                        </div>
                        <div>
                          <span className="text-indigo-600 font-medium">教师修正：</span>
                          <span className="text-indigo-800 font-medium">{rec.teacher_scores}</span>
                        </div>
                        {rec.reason && (
                          <div className="text-xs text-slate-600 italic mt-1 pl-4 border-l-2 border-indigo-300">
                            {rec.reason}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 text-[10px] text-indigo-500 text-center">
                  以上记录将在AI评估新回答时作为参考，使评分更贴近您的判断标准
                </div>
              </div>
            )}
          </div>
        )}

        {/* Topic cards */}
        {studentTopics.map(t => {
          const resp = respMap[t.id];
          const scores = resp ? (resp.teacher_dimension_scores || resp.ai_dimension_scores) : null;
          const tAvg = avgRating(scores);
          const tBadge = overallBadge(tAvg);
          const isExpanded = expandedTopic === t.id;
          const aiNote = resp?.ai_note || '';
          const teacherNote = resp?.teacher_note || '';
          const isReviewed = resp?.teacher_reviewed || false;
          const suggestedTags = resp?.ai_suggested_tags || [];
          const teacherTags = resp?.teacher_tags || [];

          return (
            <div key={t.id} className={`bg-white rounded-xl border overflow-hidden transition-all
              ${tAvg >= 3.5 ? 'border-green-200' : tAvg >= 2.5 ? 'border-emerald-200' : tAvg >= 1.5 ? 'border-yellow-200' : 'border-red-200'}`}>

              {/* Collapsed header */}
              <div
                onClick={() => setExpandedTopic(isExpanded ? null : t.id)}
                className="px-4 py-3 cursor-pointer flex items-center gap-3 hover:bg-slate-50/50 transition-colors"
              >
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center text-xs font-bold shrink-0 ${tBadge.cls}`}>
                  {tBadge.label}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-800">辩题{t.order}</span>
                    <span className="text-xs text-slate-500 truncate">{t.title}</span>
                    <span className="text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">{t.topic_type}</span>
                    {isReviewed && (
                      <span className="text-[10px] bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded font-medium">已评</span>
                    )}
                  </div>
                  {/* Dimension pills */}
                  {scores && (
                    <div className="flex gap-1.5 mt-1.5">
                      {Object.entries(scores).map(([dim, rating]) => {
                        const rc = ratingColor(rating);
                        return (
                          <span key={dim} className={`text-[10px] px-1.5 py-0.5 rounded ${rc.bg} ${rc.text} font-medium`}>
                            {DIM_LABELS[dim] || dim} {rating}
                          </span>
                        );
                      })}
                    </div>
                  )}
                  {!isExpanded && (
                    <div className={`text-xs mt-1 truncate max-w-lg ${isReviewed ? 'text-indigo-500' : 'text-slate-400'}`}>
                      {isReviewed ? (teacherNote || '（教师已评分）') : aiNote}
                    </div>
                  )}
                </div>
                <span className={`text-slate-300 transition-transform ${isExpanded ? 'rotate-180' : ''}`}>▾</span>
              </div>

              {/* Expanded detail */}
              {isExpanded && (
                <div className="px-4 pb-4 border-t border-slate-100">
                  {/* Dimension score cards */}
                  {scores && (
                    <div className="mt-3 flex gap-2 flex-wrap">
                      {Object.entries(scores).map(([dim, rating]) => {
                        const rc = ratingColor(rating);
                        const rawReasoning = resp?.ai_reasoning?.[dim];
                        // ai_reasoning values can be a string or an object {evidence, reasoning, rating}
                        const reasoningText = typeof rawReasoning === 'object' && rawReasoning !== null
                          ? (rawReasoning.reasoning || rawReasoning.evidence || '')
                          : (rawReasoning || '');
                        const evidenceText = typeof rawReasoning === 'object' && rawReasoning !== null
                          ? (rawReasoning.evidence || '')
                          : '';
                        return (
                          <div key={dim} className={`rounded-lg p-2.5 border ${rc.border} ${rc.bg} min-w-[140px] flex-1`}>
                            <div className="flex items-center justify-between mb-1">
                              <span className={`text-xs font-semibold ${rc.text}`}>{DIM_LABELS[dim] || dim}</span>
                              <span className={`text-lg font-bold ${rc.text}`}>{rating}</span>
                            </div>
                            {evidenceText && (
                              <div className="text-[10px] text-slate-500 italic mb-1 leading-relaxed">{evidenceText}</div>
                            )}
                            {reasoningText && (
                              <div className="text-[11px] text-slate-600 leading-relaxed">{reasoningText}</div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Student text + AI analysis */}
                  <div className="mt-3 grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-xs font-medium text-slate-500 mb-1.5">学生作答（原始）</div>
                      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-900 min-h-[60px] leading-relaxed">
                        {resp?.raw_text || '（无作答内容）'}
                      </div>
                      {resp?.cleaned_text && (
                        <>
                          <div className="text-xs font-medium text-slate-500 mb-1.5 mt-2">清洗后文本</div>
                          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-900 min-h-[40px] leading-relaxed">
                            {resp.cleaned_text}
                          </div>
                        </>
                      )}
                    </div>
                    <div>
                      <div className="text-xs font-medium text-slate-500 mb-1.5">AI 分析</div>
                      <div className={`rounded-lg p-3 text-sm min-h-[60px] border leading-relaxed
                        ${tAvg >= 3.5 ? 'bg-green-50 border-green-200 text-green-800'
                          : tAvg >= 2 ? 'bg-amber-50 border-amber-200 text-amber-900'
                          : 'bg-red-50 border-red-200 text-red-900'}`}>
                        {aiNote || '评估完成，请查看各维度评分。'}
                      </div>
                      {suggestedTags.length > 0 && (
                        <div className="mt-2">
                          <div className="text-[11px] text-slate-400 mb-1">AI推荐标签：</div>
                          <div className="flex gap-1 flex-wrap">
                            {suggestedTags.map(tag => (
                              <span key={tag} className="text-[10px] bg-purple-50 text-purple-600 border border-purple-200 px-1.5 py-0.5 rounded">{tag}</span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Teacher note display */}
                  {isReviewed && teacherNote && (
                    <div className="mt-3 bg-indigo-50 border border-indigo-200 rounded-lg p-3">
                      <div className="text-xs font-medium text-indigo-600 mb-1">教师批注</div>
                      <div className="text-sm text-indigo-900 leading-relaxed whitespace-pre-wrap">{teacherNote}</div>
                    </div>
                  )}

                  {/* ── Teacher Review Panel ──────────── */}
                  <TeacherPanel
                    topic={t}
                    response={resp}
                    suggestedTags={suggestedTags}
                    teacherTags={teacherTags}
                    allTags={tags}
                    refreshTags={refreshTags}
                    onSubmit={submitReview}
                  />
                </div>
              )}
            </div>
          );
        })}

        {/* Navigation */}
        <div className="flex justify-between items-center">
          <button
            onClick={() => { if (currentStudentIdx > 0) { setStudentIdx(currentStudentIdx - 1); setExpandedTopic(null); } }}
            disabled={currentStudentIdx === 0}
            className="px-5 py-2 rounded-lg border border-slate-200 bg-white text-slate-600 text-sm disabled:text-slate-300 disabled:cursor-default cursor-pointer"
          >← 上一位</button>
          <span className="text-sm text-slate-400">{currentStudentIdx + 1} / {students.length}</span>
          <button
            onClick={() => { if (currentStudentIdx < students.length - 1) { setStudentIdx(currentStudentIdx + 1); setExpandedTopic(null); } }}
            disabled={currentStudentIdx === students.length - 1}
            className="px-5 py-2 rounded-lg border border-slate-200 bg-white text-slate-600 text-sm disabled:text-slate-300 disabled:cursor-default cursor-pointer"
          >下一位 →</button>
        </div>
      </div>
    </div>
  );
}

/* ── Teacher Review Panel (inline component) ─────────────── */
function TeacherPanel({ topic, response, suggestedTags, teacherTags, allTags, refreshTags, onSubmit }) {
  const aiScores = response?.ai_dimension_scores || {};
  const teacherScores = response?.teacher_dimension_scores || {};
  const currentScores = Object.keys(teacherScores).length > 0 ? { ...teacherScores } : { ...aiScores };

  const [dimScores, setDimScores] = useState(currentScores);
  const [selectedTags, setSelectedTags] = useState(teacherTags || []);
  const [note, setNote] = useState(response?.teacher_note || '');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showLibrary, setShowLibrary] = useState(false);
  const [customTag, setCustomTag] = useState('');

  if (!response) return <div className="mt-3 text-sm text-slate-400">暂无作答记录</div>;

  const allDims = [...new Set([...Object.keys(aiScores), ...Object.keys(dimScores)])];

  const toggleTag = (tag) => {
    setSelectedTags(prev => prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]);
  };

  const addCustomTag = () => {
    const t = customTag.trim();
    if (t && !selectedTags.includes(t)) {
      setSelectedTags(prev => [...prev, t]);
    }
    setCustomTag('');
  };

  // Library tags that aren't already in selectedTags or suggestedTags
  const suggestedSet = new Set(suggestedTags);
  const selectedSet = new Set(selectedTags);
  const libraryTags = (allTags || [])
    .filter(t => !suggestedSet.has(t.name) && !selectedSet.has(t.name))
    .sort((a, b) => (b.use_count || 0) - (a.use_count || 0))
    .slice(0, 12);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSubmit(response.id, {
        dimension_scores: dimScores,
        tags: selectedTags,
        note,
      });
      setSaved(true);
      refreshTags();
      setTimeout(() => setSaved(false), 2500);
    } catch (e) { console.error(e); }
    setSaving(false);
  };

  const RATINGS = ['A+', 'A', 'A-', 'B+', 'B', 'B-'];

  return (
    <div className="mt-3 p-3 bg-slate-50 rounded-lg border border-slate-200">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs font-semibold text-slate-500">教师评分（按维度调整等级）</div>
        {saved && (
          <span className="text-xs text-green-700 bg-green-100 px-2 py-0.5 rounded font-medium animate-pulse">
            已保存
          </span>
        )}
      </div>

      {/* Dimension rating selectors */}
      <div className="flex gap-3 flex-wrap mb-3">
        {allDims.map(dim => {
          const current = dimScores[dim] || '';
          const aiRating = aiScores[dim] || '';
          return (
            <div key={dim} className="flex items-center gap-2">
              <span className="text-xs text-slate-600 min-w-[60px]">{DIM_LABELS[dim] || dim}</span>
              <div className="flex gap-1">
                {RATINGS.map(r => {
                  const rc = ratingColor(r);
                  const isSelected = current === r;
                  const isAi = aiRating === r && !isSelected;
                  return (
                    <button key={r}
                      onClick={() => setDimScores({ ...dimScores, [dim]: r })}
                      className={`w-7 h-7 rounded text-xs font-bold cursor-pointer transition-all
                        ${isSelected ? `${rc.bg} ${rc.text} ring-2 ring-indigo-400` : isAi ? `${rc.bg} ${rc.text} opacity-50` : 'bg-white border border-slate-200 text-slate-400 hover:bg-slate-50'}`}>
                      {r}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Suggested tags (AI) */}
      {suggestedTags.length > 0 && (
        <div className="mb-2">
          <div className="text-[11px] text-slate-400 mb-1.5">AI推荐标签（点击选用）：</div>
          <div className="flex gap-1.5 flex-wrap">
            {suggestedTags.map(tag => (
              <button key={tag} onClick={() => toggleTag(tag)}
                className={`px-2.5 py-1 rounded-full text-xs cursor-pointer transition-all
                  ${selectedTags.includes(tag)
                    ? 'border border-indigo-400 bg-indigo-50 text-indigo-700 font-medium'
                    : 'border border-dashed border-purple-300 bg-purple-50 text-purple-600'}`}>
                {selectedTags.includes(tag) ? '✓ ' : ''}{tag}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Library tags */}
      <div className="mb-2">
        <button onClick={() => setShowLibrary(!showLibrary)}
          className="text-[11px] text-slate-400 hover:text-slate-600 cursor-pointer mb-1.5">
          {showLibrary ? '收起标签库 ▴' : '从标签库选用 ▾'}
        </button>
        {showLibrary && libraryTags.length > 0 && (
          <div className="flex gap-1.5 flex-wrap">
            {libraryTags.map(t => (
              <button key={t.id} onClick={() => toggleTag(t.name)}
                className="px-2.5 py-1 rounded-full text-xs cursor-pointer transition-all
                  border border-slate-200 bg-white text-slate-600 hover:bg-slate-50">
                {t.name}
                <span className="text-[9px] text-slate-400 ml-1">({t.use_count})</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Custom tag input */}
      <div className="flex gap-1.5 mb-3">
        <input
          placeholder="自定义标签..."
          value={customTag}
          onChange={e => setCustomTag(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addCustomTag(); } }}
          className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 outline-none focus:ring-1 focus:ring-indigo-300 w-40"
        />
        <button onClick={addCustomTag} disabled={!customTag.trim()}
          className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white text-slate-500 hover:bg-slate-50 disabled:opacity-30 cursor-pointer">
          + 添加
        </button>
      </div>

      {/* Selected tags summary */}
      {selectedTags.length > 0 && (
        <div className="mb-3">
          <div className="text-[11px] text-slate-400 mb-1">已选标签：</div>
          <div className="flex gap-1.5 flex-wrap">
            {selectedTags.map(tag => (
              <span key={tag} className="inline-flex items-center gap-1 text-xs border border-indigo-400 bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full font-medium">
                {tag}
                <button onClick={() => toggleTag(tag)} className="text-indigo-400 hover:text-indigo-600 cursor-pointer text-[10px]">×</button>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Note + Save */}
      <div className="flex gap-2 items-end">
        <textarea
          placeholder="补充批注（可选）— 记录你对这个学生的个性化观察"
          value={note}
          onChange={e => setNote(e.target.value)}
          className="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2 resize-none min-h-[36px] outline-none focus:ring-1 focus:ring-indigo-300"
        />
        <button
          onClick={handleSave}
          disabled={saving}
          className={`px-4 py-2 rounded-lg text-white text-sm font-medium transition-colors shrink-0
            ${saved ? 'bg-green-600' : 'bg-indigo-600 hover:bg-indigo-700'} disabled:opacity-50`}
        >
          {saving ? '保存中...' : saved ? '已保存' : '确认评分'}
        </button>
      </div>
    </div>
  );
}
