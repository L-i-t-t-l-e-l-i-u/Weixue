import { useState, useEffect, useRef, useCallback } from 'react';
import useStore from '../stores/gradingStore';
import * as api from '../api/client';

const ratingToNum = { 'A+': 4, 'A': 3.5, 'A-': 3, 'B+': 2.5, 'B': 2, 'B-': 1 };
const avgRating = (scores) => {
  if (!scores) return 0;
  const vals = Object.values(scores).map(r => ratingToNum[r] || 0);
  return vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
};
const ratingLabel = (avg) => {
  if (avg >= 3.5) return { text: '优秀', cls: 'text-green-600' };
  if (avg >= 2.5) return { text: '良好', cls: 'text-emerald-600' };
  if (avg >= 1.5) return { text: '待提升', cls: 'text-yellow-600' };
  if (avg > 0) return { text: '薄弱', cls: 'text-red-600' };
  return { text: '未评', cls: 'text-slate-400' };
};

const DIM_LABELS = {
  clarity: '清晰性', interpretation: '解释力', evidence_awareness: '证据意识',
  relevance: '相关性', inference: '因果推理', evidence_use: '证据使用',
  argument_evaluation: '论证质量', depth_breadth: '深度广度', self_regulation: '反思调节',
};

export default function CommentsPage() {
  const { students, topics, responses, currentStudentIdx, setStudentIdx, courseId, loadCourse } = useStore();
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState(''); // '' | 'saving' | 'saved'
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchResult, setBatchResult] = useState(null);
  const saveTimer = useRef(null);

  const student = students[currentStudentIdx];

  // Set initial draft only when component first mounts with a student
  const initializedRef = useRef(false);
  useEffect(() => {
    if (student && !initializedRef.current) {
      setDraft(student.comment_draft || '');
      initializedRef.current = true;
    }
  }, [student]);

  // Debounced auto-save
  const autoSave = useCallback((text) => {
    if (!student || !courseId) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    setSaveStatus('saving');
    saveTimer.current = setTimeout(async () => {
      try {
        await api.saveCommentDraft(courseId, student.id, text);
        setSaveStatus('saved');
        setTimeout(() => setSaveStatus(''), 2000);
      } catch {
        setSaveStatus('');
      }
    }, 800);
  }, [student?.id, courseId]);

  const handleDraftChange = (e) => {
    const text = e.target.value;
    setDraft(text);
    autoSave(text);
  };

  if (students.length === 0) return null;

  const resps = responses[student?.id] || [];
  const respMap = {};
  resps.forEach(r => { respMap[r.topic_id] = r; });

  // Per-topic teacher data
  let totalAvg = 0, topicCount = 0, reviewedCount = 0;
  const topicDetails = [];
  topics.forEach(t => {
    const r = respMap[t.id];
    if (!r || !r.raw_text || !r.raw_text.trim()) return;
    const scores = r.teacher_dimension_scores || r.ai_dimension_scores;
    const isReviewed = r.teacher_reviewed || false;
    if (isReviewed) reviewedCount++;
    if (scores) {
      const avg = avgRating(scores);
      totalAvg += avg;
      topicCount++;
      topicDetails.push({
        topic: t, avg, scores, isReviewed,
        tags: r.teacher_tags || [],
        note: r.teacher_note || '',
      });
    }
  });
  const studentAvg = topicCount > 0 ? totalAvg / topicCount : 0;
  const rl = ratingLabel(studentAvg);

  const generate = async () => {
    if (!student) return;
    setLoading(true);
    try {
      const r = await api.generateComment(courseId, student.id);
      await loadCourse(courseId);
      setDraft(r.draft);
      setSaveStatus('');
    } catch (e) {
      setDraft('生成失败，请确保已完成教师批改。');
    }
    setLoading(false);
  };

  const batchGenerate = async () => {
    setBatchLoading(true);
    setBatchResult(null);
    try {
      const r = await api.batchGenerateComments(courseId);
      setBatchResult(r);
      await loadCourse(courseId);
      // After reload, show current student's draft
      const updated = useStore.getState().students[currentStudentIdx];
      if (updated) setDraft(updated.comment_draft || '');
    } catch {
      setBatchResult({ results: [], error: '批量生成失败' });
    }
    setBatchLoading(false);
  };

  // Per-student info for selector
  const studentInfo = students.map((st, i) => {
    const ss = responses[st.id] || [];
    const sm = {};
    ss.forEach(r => { sm[r.topic_id] = r; });
    let avg = 0, cnt = 0, reviewed = 0;
    topics.forEach(t => {
      const r = sm[t.id];
      if (!r || !r.raw_text || !r.raw_text.trim()) return;
      if (r.teacher_reviewed) reviewed++;
      const scores = r.teacher_dimension_scores || r.ai_dimension_scores;
      if (scores) { avg += avgRating(scores); cnt++; }
    });
    const stAvg = cnt > 0 ? avg / cnt : 0;
    return { name: st.name, idx: i, avg: stAvg, reviewed, hasDraft: !!st.comment_draft };
  });

  const handleStudentChange = (i) => {
    setStudentIdx(i);
    const st = students[i];
    setDraft(st?.comment_draft || '');
    setSaveStatus('');
  };

  return (
    <div className="flex flex-col gap-5">
      {/* ── Top bar: student selector + batch button ──────── */}
      <div className="bg-white rounded-xl p-3 border border-slate-200 flex items-center gap-2 flex-wrap">
        <span className="text-xs text-slate-500 shrink-0">选择学生：</span>
        <div className="flex gap-1.5 flex-wrap flex-1">
          {studentInfo.map((si, i) => {
            const siLabel = ratingLabel(si.avg);
            return (
              <button key={i} onClick={() => handleStudentChange(i)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer
                  ${i === currentStudentIdx
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>
                {si.name}
                <span className={`ml-1.5 ${i === currentStudentIdx ? 'text-indigo-200' : siLabel.cls}`}>
                  {si.avg > 0 ? siLabel.text : ''}
                </span>
                {si.hasDraft && (
                  <span className={`ml-1 text-[10px] ${i === currentStudentIdx ? 'text-indigo-200' : 'text-green-600'}`}>✓</span>
                )}
                {si.reviewed > 0 && !si.hasDraft && (
                  <span className={`ml-1 text-[10px] ${i === currentStudentIdx ? 'text-indigo-200' : 'text-indigo-500'}`}>
                    {si.reviewed}评
                  </span>
                )}
                {si.reviewed === 0 && si.avg === 0 && !si.hasDraft && (
                  <span className={`ml-1 text-[10px] ${i === currentStudentIdx ? 'text-indigo-200' : 'text-slate-400'}`}>未评</span>
                )}
              </button>
            );
          })}
        </div>
        <button
          onClick={batchGenerate}
          disabled={batchLoading}
          className="text-xs px-4 py-2 rounded-lg bg-emerald-600 text-white font-medium cursor-pointer hover:bg-emerald-700 disabled:opacity-50 transition-colors shrink-0"
        >
          {batchLoading ? '生成中...' : '一键生成全部评语'}
        </button>
      </div>

      {/* Batch result banner */}
      {batchResult && (
        <div className={`rounded-xl p-3 border text-xs ${batchResult.results?.some(r => !r.error) ? 'bg-green-50 border-green-200 text-green-800' : 'bg-amber-50 border-amber-200 text-amber-800'}`}>
          <div className="font-medium mb-1">批量生成完成</div>
          <div className="flex flex-wrap gap-2">
            {batchResult.results?.map(r => (
              <span key={r.student_id} className={r.error ? 'text-amber-600' : 'text-green-700'}>
                {r.student_name}: {r.error ? r.error : '✓'}
              </span>
            ))}
          </div>
          <button onClick={() => setBatchResult(null)} className="text-[10px] text-slate-400 hover:text-slate-600 cursor-pointer mt-1">关闭</button>
        </div>
      )}

      {/* ── Main content ──────────────────────────────────── */}
      {!student && <div className="text-slate-400 text-center py-10">请选择学生</div>}
      {student && (
        <div className="grid grid-cols-2 gap-5">
          {/* Left: teacher data context */}
          <div className="flex flex-col gap-4">
            <div className="bg-white rounded-xl p-4 border border-slate-200">
              <div className="text-sm font-semibold text-slate-600 mb-3">评估结果摘要</div>
              <div className={`text-xl font-bold mb-2 ${rl.cls}`}>
                {rl.text} <span className="text-sm text-slate-400">（均分 {studentAvg.toFixed(1)}/4.0）</span>
              </div>
              <div className="text-xs text-slate-500 mb-2">
                教师已批改 <b className="text-indigo-600">{reviewedCount}</b> / {topicCount} 个辩题
              </div>
            </div>

            <div className="bg-white rounded-xl p-4 border border-slate-200">
              <div className="text-sm font-semibold text-slate-600 mb-3">教师批改记录</div>
              {topicDetails.length === 0 && (
                <div className="text-xs text-slate-400">暂无评估数据</div>
              )}
              {topicDetails.map(({ topic, avg, scores, isReviewed, tags, note }) => (
                <div key={topic.id} className="mb-3 pb-3 border-b border-slate-50 last:border-0 last:pb-0 last:mb-0">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-xs font-medium text-slate-700">辩题{topic.order}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${isReviewed ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-500'}`}>
                      {isReviewed ? '已批改' : '仅AI'}
                    </span>
                    <span className={`text-[10px] ${ratingLabel(avg).cls}`}>{ratingLabel(avg).text}</span>
                  </div>
                  {scores && (
                    <div className="flex gap-1 flex-wrap mb-1.5">
                      {Object.entries(scores).map(([dim, rating]) => (
                        <span key={dim} className="text-[10px] bg-slate-50 text-slate-600 px-1.5 py-0.5 rounded">
                          {DIM_LABELS[dim] || dim} {rating}
                        </span>
                      ))}
                    </div>
                  )}
                  {tags.length > 0 && (
                    <div className="flex gap-1 flex-wrap mb-1">
                      {tags.map(tag => (
                        <span key={tag} className="text-[10px] bg-indigo-50 text-indigo-600 border border-indigo-200 px-1.5 py-0.5 rounded">{tag}</span>
                      ))}
                    </div>
                  )}
                  {note && (
                    <div className="text-[11px] text-indigo-700 bg-indigo-50/50 rounded px-2 py-1 leading-relaxed">{note}</div>
                  )}
                  {!isReviewed && !tags.length && !note && (
                    <div className="text-[10px] text-slate-400">（教师尚未批改此题，评语将仅参考AI评分）</div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Right: comment editor */}
          <div className="flex flex-col gap-3">
            <div className="flex justify-between items-center">
              <h3 className="text-sm font-semibold text-slate-800">{student.name} 的评语</h3>
              <div className="flex items-center gap-2">
                {saveStatus === 'saving' && <span className="text-[10px] text-slate-400">保存中...</span>}
                {saveStatus === 'saved' && <span className="text-[10px] text-green-600">已自动保存</span>}
                {draft && !loading && (
                  <button onClick={generate} disabled={loading}
                    className="text-xs bg-slate-50 text-slate-500 border border-slate-200 rounded-md px-2.5 py-1 cursor-pointer hover:bg-slate-100 disabled:opacity-50">
                    {loading ? '生成中...' : '重新生成'}
                  </button>
                )}
              </div>
            </div>

            {!draft && !loading && (
              <div className="flex-1 flex flex-col items-center justify-center min-h-[280px] bg-slate-50 rounded-xl border border-dashed border-slate-300">
                <div className="text-slate-400 text-sm mb-4 text-center px-8 leading-relaxed">
                  {reviewedCount > 0
                    ? `已批改 ${reviewedCount} 个辩题，可以生成评语了`
                    : '请先在「评分」页面完成至少一个辩题的教师批改'}
                </div>
                <button
                  onClick={generate}
                  disabled={reviewedCount === 0 || loading}
                  className="px-6 py-2.5 rounded-lg bg-indigo-600 text-white text-sm font-medium cursor-pointer hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  生成评语
                </button>
              </div>
            )}

            {loading && (
              <div className="flex-1 flex flex-col items-center justify-center min-h-[280px] bg-slate-50 rounded-xl border border-dashed border-indigo-300">
                <div className="text-indigo-500 text-sm animate-pulse">AI 正在根据批改记录生成评语...</div>
              </div>
            )}

            {draft && !loading && (
              <textarea
                value={draft}
                onChange={handleDraftChange}
                className="flex-1 text-sm leading-7 border border-slate-200 rounded-xl p-4 resize-none outline-none min-h-[280px] focus:ring-1 focus:ring-indigo-300"
              />
            )}

            {draft && !loading && (
              <div className="flex gap-2 justify-end">
                <button className="px-5 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium cursor-pointer hover:bg-indigo-700">发送给学生</button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
