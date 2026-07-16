import { useEffect } from 'react';
import useStore from './stores/gradingStore';
import GradingPage from './pages/GradingPage';
import CommentsPage from './pages/CommentsPage';
import PrepPage from './pages/PrepPage';
import ReportPage from './pages/ReportPage';
import LibraryPage from './pages/LibraryPage';

const TABS = [
  { key: 'grading',  label: '智能评估', icon: '🧠' },
  { key: 'comments', label: '评语生成', icon: '💬' },
  { key: 'prep',     label: '备课辅助', icon: '📋' },
  { key: 'report',   label: '学情报告', icon: '📊' },
  { key: 'library',  label: '标签库',   icon: '🏷️' },
];

const TAB_DESC = {
  grading:  'AI已完成多维度认知评估。每题按维度给出A/B/C/D等级，请逐份审阅并修改。',
  comments: '基于您的评分和批注，AI生成评语草稿。请编辑后发送给学生。',
  prep:     '基于您确认的评估数据，AI按维度薄弱项整理讲评建议。',
  report:   '基于教师审核后的最终评分，生成班级思辨能力分析报告。',
  library:  '管理评语标签库。基础标签来自教研经验，AI新增标签由评估过程中的教师选择自动入库。',
};

const TIER_LABEL = { basic: '低年级', developing: '中年级', advancing: '高年级' };

export default function App() {
  const { course, currentTab, setTab, loading, assessing, assessmentProgress, loadAllCourses, runAssessment, resetAll } = useStore();

  useEffect(() => { loadAllCourses(); }, []);

  if (loading && !course) {
    return (
      <div className="min-h-screen flex items-center justify-center text-slate-400">
        <div className="text-center">
          <div className="text-4xl mb-4 animate-pulse">📚</div>
          <div>加载数据中...</div>
        </div>
      </div>
    );
  }

  if (!course) {
    return (
      <div className="min-h-screen flex items-center justify-center text-slate-400">
        <div className="text-center">
          <div className="text-4xl mb-4">📭</div>
          <div>暂无课程数据。请先运行 <code className="bg-slate-200 px-2 py-1 rounded text-sm">python seed.py</code> 初始化。</div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-100">
      {/* ── Header ─────────────────────────────────────── */}
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-6 py-3 flex justify-between items-center">
          <div className="flex items-center gap-2">
            <span className="bg-indigo-100 text-indigo-700 text-xs font-bold px-2 py-1 rounded">DEMO</span>
            <h1 className="text-lg font-bold text-slate-900 m-0">维学思辨星 · 少儿思辨能力评估系统</h1>
          </div>
          <div className="text-right text-xs text-slate-400">
            <div>{course.class_name} · {course.title}</div>
            <div className="text-slate-300">教师端</div>
          </div>
        </div>
      </header>

      {/* ── Tabs ───────────────────────────────────────── */}
      <nav className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-6 flex gap-1">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors cursor-pointer bg-transparent
                ${currentTab === t.key
                  ? 'border-indigo-600 text-indigo-700'
                  : 'border-transparent text-slate-500 hover:text-slate-700 hover:bg-slate-50'}`}
            >
              <span className="mr-1">{t.icon}</span>{t.label}
            </button>
          ))}
          <div className="flex-1" />
          {currentTab === 'grading' && !assessing && (
            <div className="flex gap-2 my-1.5">
              <button
                onClick={() => { if (window.confirm('确定要重置所有评估数据吗？所有评分、批注、标签将恢复到初始状态。')) resetAll(); }}
                className="px-3 py-1.5 text-xs font-medium rounded-lg border border-red-200 text-red-600 bg-white hover:bg-red-50 transition-colors"
              >
                ↺ 重置
              </button>
              <button
                onClick={runAssessment}
                className="px-4 py-1.5 text-xs font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
              >
                🤖 AI评估全班
              </button>
            </div>
          )}
        </div>
      </nav>

      {/* ── Assessment Progress Bar ──────────────────────── */}
      {assessing && assessmentProgress && (
        <div className="bg-indigo-50 border-b border-indigo-200">
          <div className="max-w-7xl mx-auto px-6 py-3">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
                <span className="text-sm font-medium text-indigo-800">
                  AI评估进行中 — {assessmentProgress.completed} / {assessmentProgress.total}
                </span>
              </div>
              <div className="flex items-center gap-4 text-xs text-indigo-600">
                {assessmentProgress.llm_calls > 0 && <span>LLM调用 {assessmentProgress.llm_calls} 次</span>}
                {assessmentProgress.skipped > 0 && <span>跳过 {assessmentProgress.skipped}</span>}
                {assessmentProgress.errors > 0 && <span className="text-red-500">异常 {assessmentProgress.errors}</span>}
              </div>
            </div>
            <div className="w-full bg-indigo-100 rounded-full h-2.5 overflow-hidden">
              <div
                className="bg-indigo-600 h-full rounded-full transition-all duration-300 ease-out"
                style={{ width: `${assessmentProgress.total > 0 ? (assessmentProgress.completed / assessmentProgress.total * 100) : 0}%` }}
              />
            </div>
            <div className="text-[11px] text-indigo-500 mt-1.5 text-right">
              {assessmentProgress.total > 0 ? Math.round(assessmentProgress.completed / assessmentProgress.total * 100) : 0}%
            </div>
          </div>
        </div>
      )}
      {assessing && !assessmentProgress && (
        <div className="bg-indigo-50 border-b border-indigo-200">
          <div className="max-w-7xl mx-auto px-6 py-3 flex items-center gap-2">
            <div className="w-4 h-4 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
            <span className="text-sm text-indigo-800">正在启动评估任务...</span>
          </div>
        </div>
      )}

      {/* ── Description ────────────────────────────────── */}
      <div className="max-w-7xl mx-auto px-6 pt-4 pb-2 text-sm text-slate-500">
        {TAB_DESC[currentTab]}
      </div>

      {/* ── Content ────────────────────────────────────── */}
      <main className="max-w-7xl mx-auto px-6 pb-10">
        {currentTab === 'grading'  && <GradingPage />}
        {currentTab === 'comments' && <CommentsPage />}
        {currentTab === 'prep'     && <PrepPage />}
        {currentTab === 'report'   && <ReportPage />}
        {currentTab === 'library'  && <LibraryPage />}
      </main>
    </div>
  );
}
