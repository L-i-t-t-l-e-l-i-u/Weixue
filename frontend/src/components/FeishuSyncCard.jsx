import { useCallback, useEffect, useState } from 'react';
import * as api from '../api/client';

const TABLE_LABELS = {
  courses: '班级', topics: '辩题', students: '学生', responses: '作答', prep_plans: '讲评计划',
};

/**
 * Feishu Bitable sync status card — shared by 智能评估 and 备课辅助 so the
 * two pages can never drift on configuration/binding counts.
 */
export default function FeishuSyncCard({ courseId }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState('');

  const refresh = useCallback(async () => {
    setError('');
    try {
      setStatus(await api.getFeishuBitableStatus());
    } catch (e) {
      setError(e?.response?.data?.detail || '无法获取飞书同步状态');
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const runSync = async () => {
    setSyncing(true);
    setSyncResult('');
    try {
      const r = await api.syncFeishuBitable(courseId);
      const synced = r.synced ?? r.records?.length ?? 0;
      setSyncResult(`同步完成：新增/更新 ${synced} 条，跳过 ${r.skipped ?? 0} 条`);
      refresh();
    } catch (e) {
      setSyncResult(`同步失败：${e?.response?.data?.detail || e?.message || '未知错误'}`);
    }
    setSyncing(false);
  };

  const ready = status?.mode === 'ready';
  const bindings = status?.bindings || {};
  return (
    <div className={`rounded-xl border ${ready ? 'border-emerald-200 bg-emerald-50/50' : 'border-amber-200 bg-amber-50/50'}`}>
      <div className="px-4 py-2.5 flex items-center gap-2.5">
        <span className={`w-2 h-2 rounded-full ${ready ? 'bg-emerald-500' : 'bg-amber-400'}`} />
        <span className="text-xs font-medium text-slate-700">飞书多维表格</span>
        <span className={`text-[11px] px-2 py-0.5 rounded-full ${ready ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
          {ready ? '已配置' : status ? '待联调' : '加载中'}
        </span>
        {status?.message && <span className="text-[11px] text-slate-400">{status.message}</span>}
        <div className="ml-auto flex items-center gap-1.5">
          <button
            onClick={runSync}
            disabled={syncing || !ready}
            className={`text-[11px] px-2.5 py-1 rounded-md border font-medium transition-colors cursor-pointer
              ${ready ? 'border-emerald-300 bg-white text-emerald-700 hover:bg-emerald-50' : 'border-slate-200 bg-white text-slate-400 cursor-not-allowed'}`}
          >
            {syncing ? '同步中...' : '同步'}
          </button>
          <button
            onClick={() => setOpen(!open)}
            className="text-[11px] text-slate-400 hover:text-slate-600 cursor-pointer px-1"
          >
            {open ? '收起 ▴' : '详情 ▾'}
          </button>
        </div>
      </div>
      {error && <div className="px-4 pb-2 text-[11px] text-red-500">{error}</div>}
      {syncResult && <div className="px-4 pb-2 text-[11px] text-slate-600">{syncResult}</div>}
      {open && (
        <div className="px-4 pb-3 pt-1 border-t border-slate-100">
          {status?.mode === 'deferred' && !status?.message && (
            <div className="text-[11px] text-amber-700 mb-2">
              尚未配置多维表格（FEISHU_BITABLE_APP_TOKEN / FEISHU_BITABLE_TABLE_IDS），
              可用 <code>python -m feishu.schema --apply</code> 引导建表。
            </div>
          )}
          <div className="flex gap-4 flex-wrap">
            {Object.entries(TABLE_LABELS).map(([key, label]) => (
              <div key={key} className="text-[11px] text-slate-500">
                {label}表：<b className="text-slate-700">{bindings[key] ?? 0}</b> 条已绑定
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
