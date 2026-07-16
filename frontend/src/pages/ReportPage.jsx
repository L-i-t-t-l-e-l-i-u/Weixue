import { useState, useEffect } from 'react';
import useStore from '../stores/gradingStore';
import * as api from '../api/client';

const DIM_LABELS = {
  clarity: '清晰性', interpretation: '解释力', evidence_awareness: '证据意识',
  relevance: '相关性', inference: '因果推理', evidence_use: '证据使用',
  argument_evaluation: '论证质量', depth_breadth: '深度广度', self_regulation: '反思调节',
};

const barColor = (val) => {
  if (val >= 3.5) return 'bg-green-500';
  if (val >= 3) return 'bg-emerald-400';
  if (val >= 2.5) return 'bg-yellow-400';
  if (val > 0) return 'bg-orange-400';
  return 'bg-red-500';
};

const scoreLabel = (avg) => {
  if (avg >= 3.5) return { text: '优秀', cls: 'text-green-600' };
  if (avg >= 2.5) return { text: '良好', cls: 'text-emerald-600' };
  if (avg >= 1.5) return { text: '待提升', cls: 'text-yellow-600' };
  if (avg > 0) return { text: '薄弱', cls: 'text-red-600' };
  return { text: '未评', cls: 'text-slate-400' };
};

export default function ReportPage() {
  const { courseId } = useStore();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!courseId) return;
    api.getClassReport(courseId)
      .then(setReport)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [courseId]);

  if (loading) return <div className="text-slate-400 py-10 text-center">加载报告...</div>;
  if (!report) return <div className="text-red-500 py-10 text-center">报告加载失败</div>;

  const classLabel = scoreLabel(report.class_avg);

  return (
    <div className="flex flex-col gap-5">
      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: '参评人数', value: `${report.student_count}人`, color: 'text-slate-600' },
          { label: '班级均分', value: `${report.class_avg.toFixed(1)}/4.0`, color: classLabel.cls },
          { label: '最高均分', value: report.student_stats.length > 0 ? `${Math.max(...report.student_stats.map(s => s.avg_score)).toFixed(1)}` : '-', color: 'text-green-600' },
          { label: '辩题数', value: report.topic_stats.length, color: 'text-slate-600' },
        ].map((c, i) => (
          <div key={i} className="bg-white rounded-xl p-4 border border-slate-200">
            <div className="text-slate-400 text-xs">{c.label}</div>
            <div className={`text-xl font-bold mt-1 ${c.color}`}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* Per-topic dimension breakdown */}
      <div className="bg-white rounded-xl p-5 border border-slate-200">
        <h3 className="text-sm font-semibold text-slate-800 mb-4">各辩题维度均分</h3>
        {report.topic_stats.map(ts => (
          <div key={ts.topic_id} className="mb-4 pb-3 border-b border-slate-50 last:border-0 last:pb-0">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-sm font-medium text-slate-700">{ts.title}</span>
              <span className="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded">{ts.cognitive_tier}</span>
              {ts.uncertain > 0 && <span className="text-[10px] text-slate-400">{ts.uncertain}人存疑</span>}
            </div>
            {Object.entries(ts.avg_dimension_scores).length > 0 ? (
              <div className="space-y-1.5">
                {Object.entries(ts.avg_dimension_scores).map(([dim, val]) => (
                  <div key={dim} className="flex items-center gap-3">
                    <div className="w-20 text-xs text-slate-500 shrink-0">{DIM_LABELS[dim] || dim}</div>
                    <div className="flex-1 bg-slate-100 rounded h-4 overflow-hidden">
                      <div className={`h-full rounded transition-all ${barColor(val)}`}
                        style={{ width: `${Math.max((val / 4) * 100, 2)}%` }} />
                    </div>
                    <div className={`w-12 text-xs text-right font-semibold ${barColor(val).replace('bg-', 'text-')}`}>{val.toFixed(1)}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-xs text-slate-400">暂无评估数据</div>
            )}
          </div>
        ))}
      </div>

      {/* Per-student scores */}
      <div className="bg-white rounded-xl p-5 border border-slate-200">
        <h3 className="text-sm font-semibold text-slate-800 mb-3">学生个体评估</h3>
        <div className="grid grid-cols-3 gap-2">
          {report.student_stats.map(s => {
            const sl = scoreLabel(s.avg_score);
            return (
              <div key={s.student_id} className="p-3 rounded-lg bg-slate-50 border border-slate-100">
                <div className="flex justify-between items-center">
                  <div>
                    <span className="text-sm font-medium text-slate-700">{s.name}</span>
                    <span className="text-[10px] text-slate-400 ml-1.5">{s.grade}年级</span>
                  </div>
                  <span className={`text-sm font-bold ${sl.cls}`}>{s.avg_score > 0 ? s.avg_score.toFixed(1) : '-'}</span>
                </div>
                <div className="text-[11px] text-slate-400 mt-1">
                  {s.cognitive_tier === 'basic' ? '基础层' : s.cognitive_tier === 'developing' ? '发展层' : '进阶层'}
                  {s.uncertain > 0 ? ` · ${s.uncertain}题存疑` : ''}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Top tags */}
      {report.top_tags.length > 0 && (
        <div className="bg-white rounded-xl p-5 border border-slate-200">
          <h3 className="text-sm font-semibold text-slate-800 mb-3">高频标签</h3>
          {report.top_tags.filter(t => t.count > 0).map((t, i) => (
            <div key={t.name} className="flex items-start gap-2.5 py-2 border-b border-slate-50 last:border-0">
              <span className="bg-red-100 text-red-700 text-[11px] font-semibold px-2 py-0.5 rounded shrink-0">{t.count}次</span>
              <div>
                <div className="text-sm text-slate-800">{t.name}</div>
                <div className="text-[11px] text-slate-400">{t.source === 'ai_new' ? 'AI新增标签' : '基础标签'}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
