import { useState } from 'react';
import useStore from '../stores/gradingStore';
import * as api from '../api/client';

export default function LibraryPage() {
  const { tags, courseId, refreshTags } = useStore();
  const [editMode, setEditMode] = useState(false);
  const [mergeSet, setMergeSet] = useState([]);
  const [editTag, setEditTag] = useState(null);

  const baseCount = tags.filter(t => t.source === 'base').length;
  const aiCount = tags.filter(t => t.source === 'ai_new').length;
  const teacherCount = tags.filter(t => t.source === 'teacher').length;
  const usedCount = tags.filter(t => t.use_count > 0).length;
  const totalUses = tags.reduce((s, t) => s + t.use_count, 0);

  const toggleMerge = (id) => setMergeSet(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);

  const handleMerge = async () => {
    if (mergeSet.length < 2) return;
    const [keep, ...rest] = mergeSet;
    try {
      await api.mergeTags(keep, rest);
      await refreshTags();
    } catch (e) { console.error(e); }
    setMergeSet([]);
  };

  const handleDelete = async (id) => {
    try {
      await api.deleteTag(id);
      await refreshTags();
    } catch (e) { console.error(e); }
  };

  const handleRename = async (id, newName) => {
    if (!newName) { setEditTag(null); return; }
    try {
      await api.updateTag(id, { name: newName });
      await refreshTags();
    } catch (e) { console.error(e); }
    setEditTag(null);
  };

  return (
    <div>
      {/* Stats */}
      <div className="flex gap-4 mb-5">
        {[
          { label: '标签总数', value: tags.length, sub: `基础 ${baseCount} · AI ${aiCount} · 教师 ${teacherCount}`, color: 'text-slate-800' },
          { label: '已使用标签', value: usedCount, sub: '至少被选用过1次', color: 'text-indigo-600' },
          { label: '累计选用次数', value: totalUses, sub: '教师在评估中选用', color: 'text-emerald-600' },
        ].map((c, i) => (
          <div key={i} className="bg-white rounded-xl p-4 border border-slate-200 flex-1">
            <div className="text-slate-500 text-[11px]">{c.label}</div>
            <div className={`text-2xl font-bold mt-1 ${c.color}`}>{c.value}</div>
            <div className="text-[11px] text-slate-400 mt-0.5">{c.sub}</div>
          </div>
        ))}
      </div>

      {/* Mechanism explain */}
      <div className="bg-purple-50 rounded-xl p-3.5 border border-purple-200 mb-5">
        <div className="text-sm font-semibold text-purple-700 mb-1">标签库运作机制</div>
        <div className="text-xs text-purple-600 leading-6">
          AI在评估时为每道辩题推荐新标签。教师选用后自动入库，选用次数越多排序越靠前。
          AI可能为同类问题生成不同表述的标签——点击"管理标签"可合并语义相近的标签、重命名或删除。
          合并后使用次数自动累加，学情报告的"高频标签"模块实时引用标签库数据。
        </div>
      </div>

      {/* Tag grid */}
      <div className="bg-white rounded-xl p-5 border border-slate-200">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-sm font-semibold text-slate-800">
            全部标签 <span className="text-xs text-slate-400 font-normal">（按使用频次排序）</span>
          </h3>
          <button
            onClick={() => { setEditMode(!editMode); setMergeSet([]); setEditTag(null); }}
            className={`text-xs px-3 py-1.5 rounded-md cursor-pointer border
              ${editMode ? 'bg-red-50 border-red-200 text-red-700' : 'bg-slate-50 border-slate-200 text-slate-600'}`}>
            {editMode ? '完成管理' : '管理标签'}
          </button>
        </div>

        {editMode && (
          <div className="bg-amber-50 rounded-lg px-4 py-2.5 mb-4 border border-amber-200 text-xs text-amber-800">
            管理模式：可删除、重命名单个标签，或勾选多个语义相近的标签后点击"合并选中"将其归一。
          </div>
        )}

        {editMode && mergeSet.length >= 2 && (
          <div className="bg-purple-50 rounded-lg px-4 py-2.5 mb-4 border border-purple-200 flex justify-between items-center">
            <span className="text-xs text-purple-700">
              已选 {mergeSet.length} 个标签合并，保留项：<b>{tags.find(t => t.id === mergeSet[0])?.name}</b>
            </span>
            <div className="flex gap-2">
              <button onClick={handleMerge} className="text-xs px-3 py-1 rounded bg-purple-600 text-white font-semibold cursor-pointer">确认合并</button>
              <button onClick={() => setMergeSet([])} className="text-xs px-2.5 py-1 rounded border border-purple-200 bg-purple-50 text-purple-600 cursor-pointer">清除选择</button>
            </div>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {tags.map(t => {
            const isMergeSel = mergeSet.includes(t.id);
            const isEditing = editTag === t.id;
            return (
              <div key={t.id} className={`p-2.5 rounded-lg text-xs min-w-[150px] relative
                ${isMergeSel ? 'bg-purple-50 border border-purple-400' : t.source === 'ai_new' ? 'bg-purple-50/50 border border-purple-200' : t.source === 'teacher' ? 'bg-amber-50/50 border border-amber-200' : 'bg-slate-50 border border-slate-200'}`}>

                {editMode && (
                  <button onClick={() => handleDelete(t.id)} title="删除"
                    className="absolute top-1.5 right-1.5 w-4 h-4 rounded bg-red-100 text-red-600 text-[10px] flex items-center justify-center cursor-pointer hover:bg-red-200">×</button>
                )}

                {editMode && (
                  <div className="flex items-center gap-1.5 mb-1">
                    <input type="checkbox" checked={isMergeSel} onChange={() => toggleMerge(t.id)}
                      className="cursor-pointer accent-purple-600" />
                    <span className="text-[10px] text-purple-600">选入合并</span>
                  </div>
                )}

                {isEditing ? (
                  <RenameInline defaultName={t.name}
                    onConfirm={(n) => handleRename(t.id, n)}
                    onCancel={() => setEditTag(null)} />
                ) : (
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="font-medium">{t.name}</span>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold
                      ${t.source === 'ai_new' ? 'bg-purple-100 text-purple-600' : t.source === 'teacher' ? 'bg-amber-100 text-amber-700' : 'bg-indigo-100 text-indigo-600'}`}>
                      {t.source === 'ai_new' ? 'AI' : t.source === 'teacher' ? '教师' : '基础'}
                    </span>
                    {editMode && (
                      <button onClick={() => setEditTag(t.id)} className="text-[10px] px-1.5 py-0.5 rounded border border-slate-200 bg-white text-slate-500 cursor-pointer">改名</button>
                    )}
                  </div>
                )}

                <div className="flex gap-3 text-[11px] text-slate-400">
                  <span>使用 <b className={t.use_count > 0 ? 'text-indigo-600' : 'text-slate-400'}>{t.use_count}</b> 次</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function RenameInline({ defaultName, onConfirm, onCancel }) {
  const [val, setVal] = useState(defaultName);
  return (
    <div className="flex items-center gap-1 mb-1">
      <input value={val} onChange={e => setVal(e.target.value)} autoFocus
        className="text-xs px-1.5 py-0.5 border border-purple-300 rounded w-28"
        onKeyDown={e => { if (e.key === 'Enter') onConfirm(val); if (e.key === 'Escape') onCancel(); }} />
      <button onClick={() => onConfirm(val)} className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-600 text-white cursor-pointer">确认</button>
      <button onClick={onCancel} className="text-[10px] px-1.5 py-0.5 rounded border border-slate-200 bg-white text-slate-500 cursor-pointer">取消</button>
    </div>
  );
}
