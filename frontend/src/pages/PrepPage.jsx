import { useState, useEffect } from 'react';
import useStore from '../stores/gradingStore';
import * as api from '../api/client';

const DIM_LABELS = {
  clarity: '清晰性', interpretation: '解释力', evidence_awareness: '证据意识',
  relevance: '相关性', inference: '因果推理', evidence_use: '证据使用',
  argument_evaluation: '论证质量', depth_breadth: '深度广度', self_regulation: '反思调节',
};

const dimColor = (val) => {
  if (val >= 3.5) return 'text-green-600';
  if (val >= 2.5) return 'text-emerald-600';
  if (val >= 1.5) return 'text-yellow-600';
  return 'text-red-600';
};

export default function PrepPage() {
  const { courseId } = useStore();
  const [analytics, setAnalytics] = useState([]);
  const [lessonPlan, setLessonPlan] = useState([]);
  const [notes, setNotes] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!courseId) return;
    api.getPrepAnalytics(courseId)
      .then(data => {
        setAnalytics(data);
        // Auto-select topics with weak dimensions
        setLessonPlan(data.filter(d => d.weak_dimensions.length > 0).slice(0, 3).map(d => d.topic_id));
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [courseId]);

  if (loading) return <div className="text-slate-400 py-10 text-center">加载讲评数据...</div>;

  const problems = analytics.filter(a => a.weak_dimensions.length > 0 || Object.values(a.avg_dimension_scores).some(v => v < 2.5));
  const inPlan = problems.filter(p => lessonPlan.includes(p.topic_id));
  const available = problems.filter(p => !lessonPlan.includes(p.topic_id));

  const moveItem = (idx, dir) => {
    const ni = idx + dir;
    if (ni < 0 || ni >= lessonPlan.length) return;
    const nl = [...lessonPlan];
    [nl[idx], nl[ni]] = [nl[ni], nl[idx]];
    setLessonPlan(nl);
  };

  return (
    <div className="grid grid-cols-[3fr_2fr] gap-5">
      {/* Left: lesson plan */}
      <div className="flex flex-col gap-3">
        <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-xl p-3.5 border border-blue-200 flex gap-2.5 items-start">
          <span className="text-lg">🤖</span>
          <div className="text-sm text-blue-800">基于全班多维度评估结果，已为您整理讲评建议。请根据您的教学判断调整。</div>
        </div>

        {lessonPlan.map((topicId, idx) => {
          const cp = problems.find(p => p.topic_id === topicId);
          if (!cp) return null;
          return (
            <div key={topicId} className="bg-white rounded-xl p-4 border border-slate-200">
              <div className="flex gap-3">
                <div className="flex flex-col items-center gap-0.5 shrink-0">
                  <div className="w-6 h-6 rounded-md bg-blue-100 text-blue-700 text-xs font-bold flex items-center justify-center">{idx + 1}</div>
                  <button onClick={() => moveItem(idx, -1)} disabled={idx === 0}
                    className="text-slate-300 hover:text-slate-500 text-[11px] disabled:opacity-30 cursor-pointer">▲</button>
                  <button onClick={() => moveItem(idx, 1)} disabled={idx === lessonPlan.length - 1}
                    className="text-slate-300 hover:text-slate-500 text-[11px] disabled:opacity-30 cursor-pointer">▼</button>
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium text-sm">{cp.title}</span>
                    <span className="text-[11px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded">{cp.topic_type}</span>
                  </div>
                  {/* Dimension scores */}
                  <div className="flex gap-1.5 flex-wrap mb-2">
                    {Object.entries(cp.avg_dimension_scores).map(([dim, val]) => (
                      <span key={dim} className={`text-[11px] font-medium ${dimColor(val)}`}>
                        {DIM_LABELS[dim] || dim} {val.toFixed(1)}
                      </span>
                    ))}
                  </div>
                  {cp.weak_dimensions.length > 0 && (
                    <div className="flex gap-1 flex-wrap mb-1">
                      {cp.weak_dimensions.map(dim => (
                        <span key={dim} className="text-[11px] bg-red-50 text-red-700 border border-red-200 px-1.5 py-0.5 rounded">
                          薄弱: {DIM_LABELS[dim] || dim}
                        </span>
                      ))}
                    </div>
                  )}
                  {cp.low_students.length > 0 && (
                    <div className="text-xs text-slate-500 mb-1">低分学生：{cp.low_students.join('、')}</div>
                  )}
                  {cp.error_tags.length > 0 && (
                    <div className="flex gap-1 flex-wrap mb-2">
                      {cp.error_tags.slice(0, 4).map(et => (
                        <span key={et.tag} className="text-[11px] bg-orange-50 text-orange-700 border border-orange-200 px-1.5 py-0.5 rounded">
                          {et.tag} ({et.count})
                        </span>
                      ))}
                    </div>
                  )}
                  <textarea placeholder="添加讲解备注..." value={notes[topicId] || ''}
                    onChange={e => setNotes({ ...notes, [topicId]: e.target.value })}
                    className="w-full text-xs border border-slate-200 rounded-md px-2.5 py-1.5 resize-none min-h-[32px] outline-none focus:ring-1 focus:ring-indigo-300" />
                </div>
                <button onClick={() => setLessonPlan(lessonPlan.filter(x => x !== topicId))}
                  className="text-slate-300 hover:text-red-400 text-lg cursor-pointer leading-none">×</button>
              </div>
            </div>
          );
        })}

        <button className="w-full bg-indigo-600 text-white rounded-xl py-3 font-medium text-sm cursor-pointer hover:bg-indigo-700 transition-colors">
          确认讲评计划 →
        </button>
      </div>

      {/* Right: available topics */}
      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold text-slate-800">其他需关注辩题</h3>
        {available.map(cp => (
          <div key={cp.topic_id} className="bg-slate-50 rounded-xl p-3 border border-slate-200">
            <div className="flex justify-between mb-1">
              <span className="text-sm font-medium">{cp.title}</span>
            </div>
            <div className="flex gap-1 flex-wrap mb-1">
              {cp.weak_dimensions.map(dim => (
                <span key={dim} className="text-[10px] text-red-500">{DIM_LABELS[dim] || dim}</span>
              ))}
            </div>
            <button onClick={() => setLessonPlan([...lessonPlan, cp.topic_id])}
              className="w-full text-xs bg-white border border-slate-200 text-slate-600 rounded-md py-1.5 cursor-pointer hover:bg-slate-100 mt-1">
              + 加入讲评
            </button>
          </div>
        ))}
        <div className="bg-amber-50 rounded-xl p-3 border border-amber-200 mt-2">
          <div className="text-xs font-medium text-amber-800 mb-1">💡 教师决策门</div>
          <div className="text-xs text-amber-700">讲哪些、怎么讲、按什么顺序，由您决定。AI只负责整理数据。</div>
        </div>
      </div>
    </div>
  );
}
