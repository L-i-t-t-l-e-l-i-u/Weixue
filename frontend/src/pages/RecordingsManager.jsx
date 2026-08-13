import { useState, useEffect, useRef } from 'react';
import useStore from '../stores/gradingStore';
import * as api from '../api/client';

const SOURCE_LABEL = { audio: '🎙️ 音频', asr: '📝 转写', manual: '✍️ 手动' };

const ALLOWED_EXT = ['.mp3', '.wav', '.m4a', '.aac', '.ogg', '.amr', '.wma', '.flac', '.webm', '.mp4'];
const MAX_UPLOAD_MB = 20;          // generous hard cap for all providers
const QWEN_ASR_MAX_MB = 7;         // qwen-asr base64 payload limit

// Map upload failures to actionable guidance; always offer the paste fallback.
const classifyUploadError = (err) => {
  const status = err?.response?.status;
  const detail = err?.response?.data?.detail || err?.message || '未知错误';
  if (status === 400) return `文件格式或参数问题：${detail}。建议改用 mp3 / wav / m4a 后重试。`;
  if (status === 413) return '文件过大，请压缩或截短录音后重试。';
  if (status === 502) return `语音转写服务失败：${detail}。可在右侧「粘贴转写文本」手动录入兜底。`;
  if (status === 500 || status === 503) return `服务暂时不可用（${detail}），请稍后重试，或用右侧「粘贴转写文本」兜底。`;
  if (err?.code === 'ECONNABORTED' || /timeout/i.test(err?.message || '')) {
    return '转写超时：录音可能过长或网络不稳。请截短音频重试，或用右侧「粘贴转写文本」兜底。';
  }
  if (!err?.response) return `无法连接后端服务：${detail}。请确认后端已启动，或用右侧「粘贴转写文本」兜底。`;
  return `转写失败：${detail}`;
};

export default function RecordingsManager() {
  const { courseId, topics, students, responses, loadCourse } = useStore();
  const [topicId, setTopicId] = useState(null);
  const [studentId, setStudentId] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [text, setText] = useState('');
  const [msg, setMsg] = useState('');
  const [msgType, setMsgType] = useState('ok');  // 'ok' | 'err' — drives bar color
  const [asr, setAsr] = useState(null);           // ASR settings from backend/demo client
  const [switchingAsr, setSwitchingAsr] = useState(false);
  const [asrMsg, setAsrMsg] = useState('');
  const fileRef = useRef(null);

  useEffect(() => {
    if (!topicId && topics.length > 0) setTopicId(topics[0].id);
    if (!studentId && students.length > 0) setStudentId(students[0].id);
  }, [topics, students, topicId, studentId]);

  useEffect(() => {
    api.getAsrSettings()
      .then(setAsr)
      .catch(() => setAsr(null));
  }, []);

  const currentResp = studentId && topicId
    ? (responses[studentId] || []).find(r => r.topic_id === topicId)
    : null;

  const activeProvider = asr?.providers?.find(p => p.id === asr.provider);
  // A real provider is selected but not configured (e.g. missing API key) —
  // uploads would always fail, so block them with guidance instead.
  const providerNotReady = !!(asr && asr.provider !== 'mock' && activeProvider && !activeProvider.ready);

  const switchAsr = async (provider) => {
    const clearingDemo = provider !== 'mock' && !!asr?.demo_data_present;
    if (clearingDemo) {
      const confirmed = window.confirm(
        '切换到真实转写将清除当前数据库中的演示数据（演示课程、辩题、学生、作答），确定继续？'
      );
      if (!confirmed) return;
    }
    setSwitchingAsr(true);
    setAsrMsg('');
    try {
      const settings = await api.setAsrProvider(provider);
      setAsr(settings);
      setAsrMsg(
        provider === 'mock'
          ? '已切换到演示转写模式 ✓'
          : clearingDemo
            ? '已切换到真实转写模式 ✓（演示数据已清除）'
            : '已切换到真实转写模式 ✓'
      );
    } catch (err) {
      setAsrMsg(`切换失败：${err?.response?.data?.detail || err?.message || '未知错误'}`);
    } finally {
      setSwitchingAsr(false);
    }
  };

  const showMsg = (m, type = 'ok') => { setMsg(m); setMsgType(type); };

  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';               // allow re-selecting the same file
    if (!file || !studentId || !topicId) return;

    // ── Client-side pre-validation: fail fast with guidance, no server round-trip ──
    const ext = '.' + ((file.name.split('.').pop() || '').toLowerCase());
    if (!ALLOWED_EXT.includes(ext)) {
      showMsg(`不支持的格式 ${ext}：支持 ${ALLOWED_EXT.join(' / ')}。`, 'err');
      return;
    }
    const sizeMb = file.size / 1024 / 1024;
    if (sizeMb > MAX_UPLOAD_MB) {
      showMsg(`文件过大（${sizeMb.toFixed(1)}MB）：请压缩或截短至 ${MAX_UPLOAD_MB}MB 以内再上传。`, 'err');
      return;
    }
    if (asr?.provider === 'qwen_asr' && sizeMb > QWEN_ASR_MAX_MB) {
      showMsg(`文件过大（${sizeMb.toFixed(1)}MB）：qwen-asr 上限约 ${QWEN_ASR_MAX_MB}MB，请截短录音或切换转写模式。`, 'err');
      return;
    }

    setUploading(true);
    setMsg('');
    try {
      await api.importAudio(courseId, studentId, topicId, file);
      showMsg('转写完成，已写入作答 ✓');
      await loadCourse(courseId);
    } catch (err) {
      showMsg(classifyUploadError(err), 'err');
    } finally {
      setUploading(false);
    }
  };

  const handlePaste = async () => {
    if (!text.trim() || !studentId || !topicId) return;
    try {
      await api.importText(courseId, studentId, topicId, text.trim());
      setText('');
      showMsg('文本已保存，将进入评估 ✓');
      await loadCourse(courseId);
    } catch (err) {
      showMsg(`保存失败：${err?.response?.data?.detail || err?.message || '未知错误'}`, 'err');
    }
  };

  if (topics.length === 0 || students.length === 0) {
    return (
      <div className="bg-white rounded-xl p-8 border border-slate-200 text-center text-sm text-slate-400">
        请先在「辩题管理」和「学生管理」中录入数据
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="bg-white rounded-xl p-4 border border-slate-200">
        <div className="text-sm font-semibold text-slate-600 mb-3">选择（辩题 × 学生）</div>
        <div className="flex gap-3 flex-wrap">
          <select
            value={topicId || ''}
            onChange={e => setTopicId(parseInt(e.target.value, 10))}
            className="flex-1 min-w-[240px] text-sm border border-slate-200 rounded-lg px-3 py-2 outline-none focus:ring-1 focus:ring-indigo-300 cursor-pointer"
          >
            {topics.map(t => (
              <option key={t.id} value={t.id}>{t.order}. {t.title}</option>
            ))}
          </select>
          <select
            value={studentId || ''}
            onChange={e => setStudentId(parseInt(e.target.value, 10))}
            className="flex-1 min-w-[200px] text-sm border border-slate-200 rounded-lg px-3 py-2 outline-none focus:ring-1 focus:ring-indigo-300 cursor-pointer"
          >
            {students.map(st => (
              <option key={st.id} value={st.id}>{st.name}（{st.grade}年级）</option>
            ))}
          </select>
        </div>
      </div>

      {asr && (
        <div className="bg-white rounded-xl p-4 border border-slate-200">
          <div className="text-sm font-semibold text-slate-600 mb-2">转写模式</div>
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => switchAsr('mock')}
              disabled={switchingAsr || asr.provider === 'mock'}
              className={`text-sm px-4 py-2 rounded-lg font-medium transition-colors cursor-pointer disabled:cursor-not-allowed
                ${asr.provider === 'mock'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
            >
              演示转写（mock）
            </button>
            {(asr.providers || [])
              .filter(p => p.id !== 'mock')
              .map(p => {
                const active = asr.provider === p.id;
                const blocked = !p.ready;
                return (
                  <button
                    key={p.id}
                    onClick={() => switchAsr(p.id)}
                    disabled={switchingAsr || active || blocked}
                    title={blocked ? p.reason : ''}
                    className={`text-sm px-4 py-2 rounded-lg font-medium transition-colors cursor-pointer disabled:cursor-not-allowed
                      ${active
                        ? 'bg-indigo-600 text-white'
                        : blocked
                          ? 'bg-slate-50 text-slate-400'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
                  >
                    {p.label}
                  </button>
                );
              })}
          </div>
          <div className="text-[11px] text-slate-400 mt-2 leading-relaxed">
            {asr.demo
              ? '当前为纯前端演示模式，真实转写需连接后端服务。'
              : asr.provider === 'mock'
                ? '演示转写模式：上传音频后写入内置演示文本，不调用外部语音识别 API。'
                : activeProvider?.ready
                  ? `真实转写已就绪：${activeProvider.label}${asr.model ? `（${asr.model}）` : ''}，上传后调用真实语音识别。`
                  : `真实转写尚未就绪：${activeProvider?.reason || '请检查后端配置'}。`}
          </div>
          {asrMsg && <div className="text-[11px] text-emerald-600 mt-1">{asrMsg}</div>}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white rounded-xl p-4 border border-slate-200">
          <div className="text-sm font-semibold text-slate-600 mb-2">上传录音</div>
          <input
            ref={fileRef}
            type="file"
            accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.amr,.wma,.flac,.webm,.mp4"
            className="hidden"
            onChange={handleFile}
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading || providerNotReady}
            title={providerNotReady ? `当前转写模式未就绪：${activeProvider?.reason || '请检查配置'}` : ''}
            className={`w-full text-sm py-2.5 rounded-lg font-medium transition-colors cursor-pointer disabled:cursor-not-allowed
              ${uploading
                ? 'bg-indigo-50 text-indigo-500 border border-indigo-200'
                : providerNotReady
                  ? 'bg-slate-100 text-slate-400'
                  : 'bg-indigo-600 text-white hover:bg-indigo-700'}`}
          >
            {uploading ? '上传并转写中...' : providerNotReady ? '转写服务未就绪' : '🎙️ 选择音频文件'}
          </button>
          <div className="text-[11px] text-slate-400 mt-2">
            支持 mp3 / wav / m4a 等，系统自动转写
            {asr?.provider === 'mock'
              ? '（当前为演示转写模式，将写入演示文本）'
              : asr?.provider === 'dashscope'
                ? '（DashScope 仅支持 pcm / wav / mp3 / opus / speex / aac / amr）'
                : asr?.provider === 'qwen_asr'
                  ? '（qwen-asr 单文件建议不超过 7MB）'
                : '（真实转写模式）'}
          </div>
        </div>

        <div className="bg-white rounded-xl p-4 border border-slate-200">
          <div className="text-sm font-semibold text-slate-600 mb-2">粘贴转写文本</div>
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder="老师已有转写稿时可直接粘贴..."
            className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 resize-none min-h-[64px] outline-none focus:ring-1 focus:ring-indigo-300"
          />
          <button
            onClick={handlePaste}
            disabled={!text.trim()}
            className="w-full mt-2 text-sm py-2 rounded-lg border border-indigo-200 bg-indigo-50 text-indigo-600 font-medium cursor-pointer hover:bg-indigo-100 disabled:opacity-40"
          >
            保存文本
          </button>
        </div>
      </div>

      {msg && (
        <div className={`text-xs rounded-lg px-3 py-2 border ${
          msgType === 'err'
            ? 'text-red-600 bg-red-50 border-red-200'
            : 'text-emerald-700 bg-emerald-50 border-emerald-200'
        }`}>{msg}</div>
      )}

      <div className="bg-white rounded-xl p-4 border border-slate-200">
        <div className="text-sm font-semibold text-slate-600 mb-2">当前作答</div>
        {currentResp?.raw_text ? (
          <div>
            <div className="text-[11px] text-slate-400 mb-1">
              {SOURCE_LABEL[currentResp.source] || currentResp.source}
              {currentResp.teacher_reviewed ? ' · 已批改' : currentResp.ai_confidence !== 'uncertain' ? ' · AI已评估' : ' · 待评估'}
            </div>
            <div className="text-sm text-slate-700 bg-slate-50 border border-slate-100 rounded-lg p-3 leading-relaxed">
              {currentResp.raw_text}
            </div>
          </div>
        ) : (
          <div className="text-xs text-slate-400 py-4 text-center">该学生在本辩题下暂无作答</div>
        )}
      </div>
    </div>
  );
}
