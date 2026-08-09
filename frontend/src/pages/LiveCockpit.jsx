import { useEffect, useState } from 'react';
import useStore from '../stores/gradingStore';

const STATUS_META = {
  not_started: { label: '未发言', cls: 'bg-slate-100 text-slate-500', dot: 'bg-slate-300' },
  recording: { label: '正在发言', cls: 'bg-red-100 text-red-600', dot: 'bg-red-500 animate-pulse' },
  submitted: { label: '已发言', cls: 'bg-blue-100 text-blue-600', dot: 'bg-blue-500' },
  processing: { label: '处理中', cls: 'bg-amber-100 text-amber-600', dot: 'bg-amber-500 animate-pulse' },
  processed: { label: '已处理', cls: 'bg-green-100 text-green-700', dot: 'bg-green-500' },
};

const RATING_META = {
  good: { label: '👍 表达完整', cls: 'bg-green-600 text-white hover:bg-green-700' },
  guide: { label: '➕ 需引导', cls: 'bg-amber-500 text-white hover:bg-amber-600' },
  echo: { label: '⚠️ 复述/未表达', cls: 'bg-red-500 text-white hover:bg-red-600' },
};

const TIER_LABEL = { basic: '低', developing: '中', advancing: '高' };

export default function LiveCockpit() {
  const store = useStore();
  const {
    course, students, topics, responses, liveTopicId,
    liveStatus, liveSuggestions, liveDialogue, liveAdopted, liveBusy,
  } = store;
  const [noteDrafts, setNoteDrafts] = useState({});
  const [expanded, setExpanded] = useState({});

  useEffect(() => {
    if (course?.id) store.subscribeLiveStatus(course.id);
  }, [course?.id]);

  const topic = topics.find(t => t.id === liveTopicId) || topics[0] || null;

  const respFor = (studentId) => {
    const list = responses[studentId] || [];
    return list.find(r => r.topic_id === topic?.id) || null;
  };

  const statusOf = (studentId) => {
    const r = respFor(studentId);
    if (!r) return 'not_started';
    // liveStatus only tracks the current live session. A response that exists
    // but was never touched this session is HISTORY → the card stays 未发言.
    return liveStatus[r.id] || 'not_started';
  };

  const studentTurnCount = (rid) =>
    (liveDialogue[rid] || []).filter(t => t.role === 'student').length;

  const spokenCount = students.filter(s => statusOf(s.id) !== 'not_started').length;
  const reviewedCount = students.filter(s => {
    const r = respFor(s.id);
    return r?.teacher_reviewed;
  }).length;

  const handleAdopt = async (resp, question) => {
    await store.adoptSuggestion(resp.id, question);
  };

  const handleAssess = async (resp) => {
    await store.assessLive(resp.id);
  };

  const handleReview = async (resp, rating) => {
    await store.reviewLive(resp.id, { rating, note: noteDrafts[resp.id] || '' });
  };

  const openStudent = (studentId) => store.openStudentWindow(studentId);

  const renderSuggestion = (resp) => {
    const suggestion = liveSuggestions[resp.id];
    const adoptedQ = liveAdopted[resp.id];
    const turns = studentTurnCount(resp.id);
    const atLimit = turns >= 3;
    return (
      <div className="mt-3 rounded-xl border border-indigo-200 bg-indigo-50 p-3">
        <div className="flex items-center justify-between">
          <div className="text-xs font-semibold text-indigo-700">AI 追问建议</div>
          {liveBusy[resp.id] && <div className="text-[10px] text-indigo-400">生成中…</div>}
        </div>
        {suggestion?.echo_risk && (
          <div className="mt-1.5 rounded-md bg-red-50 border border-red-200 text-red-600 text-[11px] px-2 py-1">
            ⚠️ 疑似复述问法，建议换一种开放方式再问
          </div>
        )}
        {adoptedQ ? (
          <div className="mt-2 text-xs text-green-700 bg-white rounded-lg p-2 border border-green-200">
            已采用：请照读追问，等待学生补充（{adoptedQ}）
          </div>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {(suggestion?.questions || []).slice(0, 2).map((q, i) => (
              <li key={i} className="flex items-center gap-2">
                <span className="flex-1 text-xs text-slate-700 bg-white rounded-lg p-2 border border-slate-200">{q}</span>
                {!atLimit && (
                  <button
                    onClick={() => handleAdopt(resp, q)}
                    disabled={liveBusy[resp.id]}
                    className="shrink-0 text-[11px] font-medium text-indigo-600 border border-indigo-300 rounded-md px-2 py-1 hover:bg-indigo-100 disabled:opacity-40"
                  >
                    采用
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        <div className="mt-2 flex gap-2">
          {!atLimit && !adoptedQ && (
            <button
              onClick={() => store.suggestTurnFor(resp.id)}
              className="flex-1 text-[11px] text-indigo-500 border border-indigo-200 rounded-md py-1 hover:bg-indigo-100"
            >
              换一批
            </button>
          )}
          <button
            onClick={() => handleAssess(resp)}
            disabled={liveBusy[resp.id]}
            className="flex-1 text-[11px] font-medium bg-indigo-600 text-white rounded-md py-1 hover:bg-indigo-700 disabled:opacity-40"
          >
            {atLimit ? '已达 3 轮，直接评估' : '跳过，直接评估'}
          </button>
        </div>
      </div>
    );
  };

  const renderResult = (resp) => {
    const scores = resp.teacher_dimension_scores || resp.ai_dimension_scores || {};
    const isReviewed = resp.teacher_reviewed;
    const rating = resp.teacher_rating;
    const ratingMeta = RATING_META[rating];
    const dims = Object.entries(scores).slice(0, 5);
    return (
      <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3">
        {isReviewed ? (
          <div className="flex items-center gap-2">
            {ratingMeta ? (
              <span className={`text-xs font-bold rounded-full px-2.5 py-1 ${ratingMeta.cls}`}>{ratingMeta.label}</span>
            ) : (
              <span className="text-xs font-bold rounded-full px-2.5 py-1 bg-indigo-600 text-white">已确认</span>
            )}
            {resp.teacher_note && <span className="text-xs text-slate-500 truncate">{resp.teacher_note}</span>}
          </div>
        ) : (
          <>
            <div className="flex flex-wrap gap-1 mb-2">
              {dims.map(([dim, r]) => (
                <span key={dim} className="text-[10px] bg-slate-100 text-slate-600 rounded px-1.5 py-0.5">
                  {dim} · {r}
                </span>
              ))}
            </div>
            <div className="flex gap-1.5">
              {Object.entries(RATING_META).map(([key, meta]) => (
                <button
                  key={key}
                  onClick={() => handleReview(resp, key)}
                  disabled={liveBusy[resp.id]}
                  className={`flex-1 text-[11px] font-bold rounded-lg py-2 disabled:opacity-40 ${meta.cls}`}
                >
                  {meta.label}
                </button>
              ))}
            </div>
            <textarea
              value={noteDrafts[resp.id] || ''}
              onChange={e => setNoteDrafts(prev => ({ ...prev, [resp.id]: e.target.value }))}
              rows={1}
              placeholder="轻批注（可选）"
              className="mt-2 w-full text-[11px] border border-slate-200 rounded-lg p-1.5 outline-none focus:ring-1 focus:ring-indigo-300"
            />
            <div className="mt-1.5">
              <button
                onClick={() => setExpanded(prev => ({ ...prev, [resp.id]: !prev[resp.id] }))}
                className="text-[10px] text-indigo-500 underline"
              >
                {expanded[resp.id] ? '收起维度详情' : '展开维度详情'}
              </button>
              {expanded[resp.id] && (
                <div className="mt-1.5 text-[10px] text-slate-500 space-y-1">
                  {dims.map(([dim, r]) => (
                    <div key={dim}>{dim}：{r} — {resp.ai_reasoning?.[dim]?.reasoning || '（无推理说明）'}</div>
                  ))}
                  {resp.cleaned_text && <div>清洗稿：{resp.cleaned_text.slice(0, 80)}…</div>}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    );
  };

  const renderCard = (student) => {
    const resp = respFor(student.id);
    const status = statusOf(student.id);
    const meta = STATUS_META[status] || STATUS_META.not_started;
    const tier = TIER_LABEL[student.cognitive_tier] || '';
    const isHistory = !!resp && !liveStatus[resp.id];
    return (
      <div key={student.id} className={`rounded-2xl border bg-white p-4 shadow-sm ${status === 'recording' ? 'border-red-300' : 'border-slate-200'}`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={`w-2.5 h-2.5 rounded-full ${meta.dot}`} />
            <span className="font-semibold text-slate-800">{student.name}</span>
            {tier && <span className="text-[10px] bg-indigo-50 text-indigo-600 rounded px-1.5 py-0.5">{tier}年级段</span>}
          </div>
          <span className={`text-[10px] font-medium rounded-full px-2 py-0.5 ${meta.cls}`}>{meta.label}</span>
        </div>

        <div className="mt-2 flex items-center justify-between text-[10px] text-slate-400">
          <span>{isHistory ? '历史作答' : resp ? `${studentTurnCount(resp.id) || 1} 轮` : '等待学生发言'}</span>
          <button
            onClick={() => openStudent(student.id)}
            className="text-indigo-500 border border-indigo-200 rounded-md px-2 py-0.5 hover:bg-indigo-50"
          >
            打开学生窗口
          </button>
        </div>

        {resp && status === 'submitted' && renderSuggestion(resp)}
        {resp && (status === 'processed') && renderResult(resp)}
        {resp && status === 'processing' && (
          <div className="mt-3 text-center text-xs text-amber-500">⏳ AI 评估处理中…</div>
        )}
        {isHistory && (
          <div className="mt-3 rounded-xl border border-slate-100 bg-slate-50 p-2.5">
            <button
              onClick={() => setExpanded(prev => ({ ...prev, [`h${resp.id}`]: !prev[`h${resp.id}`] }))}
              className="text-[10px] text-slate-400 underline"
            >
              {resp.teacher_reviewed ? '历史已处理' : '历史作答'} · 查看历史评估
            </button>
            {expanded[`h${resp.id}`] && (
              <div className="mt-1.5 text-[10px] text-slate-500 space-y-0.5">
                {Object.entries(resp.teacher_dimension_scores || resp.ai_dimension_scores || {}).map(([dim, r]) => (
                  <div key={dim}>{dim} · {r}</div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  if (!course || students.length === 0) {
    return (
      <div className="text-center text-slate-400 py-16">
        暂无班级数据，请先在「工作台 → 管理」中创建班级和学生。
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-lg font-bold text-slate-800">{course?.class_name} · {course?.title}</div>
          <div className="text-xs text-slate-400 mt-0.5">课堂模式 · 直播间专用（实时状态来自学生端）</div>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <select
            value={topic?.id || ''}
            onChange={e => store.setLiveTopic(parseInt(e.target.value, 10))}
            className="border border-slate-200 rounded-lg px-2 py-1.5 outline-none"
          >
            {topics.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}
          </select>
          <span className="bg-blue-50 text-blue-600 rounded-full px-2.5 py-1 font-medium">发言 {spokenCount}/{students.length}</span>
          <span className="bg-green-50 text-green-700 rounded-full px-2.5 py-1 font-medium">已确认 {reviewedCount}/{students.length}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {students.map(renderCard)}
      </div>
    </div>
  );
}
