import { useEffect, useRef, useState } from 'react';
import * as api from '../api/client';
import { subscribeStatus, publishStatus } from '../utils/statusBus';

const IS_DEMO = import.meta.env.VITE_DEMO_MODE === 'true';

// Demo fallback transcript used when the environment cannot run real ASR.
const DEMO_TRANSCRIPT =
  '我觉得应该把老鹰放回野外。因为老鹰本来就是天空的动物，关在动物园里就只能走来走去，很不自由。';

const STATUS_TEXT = {
  not_started: '未发言',
  recording: '正在发言',
  submitted: '已提交',
  processing: '处理中',
  processed: '已处理',
};

const STATUS_COLOR = {
  not_started: 'bg-slate-100 text-slate-500',
  recording: 'bg-red-100 text-red-600',
  submitted: 'bg-blue-100 text-blue-600',
  processing: 'bg-amber-100 text-amber-600',
  processed: 'bg-green-100 text-green-700',
};

export default function StudentWindow({ studentId }) {
  const [courseId, setCourseId] = useState(null);
  const [topicId, setTopicId] = useState(null);
  const [student, setStudent] = useState(null);
  const [topic, setTopic] = useState(null);
  const [responseId, setResponseId] = useState(null);
  const [status, setStatus] = useState('not_started');
  const [turnCount, setTurnCount] = useState(0);
  const [lastTeacherQuestion, setLastTeacherQuestion] = useState('');
  const [transcript, setTranscript] = useState('');
  const [pasteText, setPasteText] = useState('');
  const [recording, setRecording] = useState(false);
  const [simCountdown, setSimCountdown] = useState(0);
  const [simNote, setSimNote] = useState('');
  const [busy, setBusy] = useState(false);

  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const responseIdRef = useRef(null);
  responseIdRef.current = responseId;

  // ── Bootstrap: locate student + topic ───────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const courses = await api.getCourses();
        const allStudents = [];
        for (const c of courses) {
          const list = await api.getStudents(c.id);
          list.forEach(s => allStudents.push({ ...s, course_id: c.id }));
        }
        const me = allStudents.find(s => s.id === Number(studentId));
        if (!me) return;
        const cid = Number(me.course_id);
        const topics = await api.getTopics(cid);
        const params = new URLSearchParams(window.location.search);
        const tid = Number(params.get('topic')) || topics[0]?.id || null;
        const t = topics.find(x => x.id === tid) || topics[0] || null;
        if (cancelled) return;
        setCourseId(cid);
        setTopicId(t ? t.id : null);
        setStudent(me);
        setTopic(t || null);

        // Resume an existing response for this student+topic.
        const resps = await api.getResponses(cid, me.id);
        const mine = resps.find(r => r.topic_id === t?.id);
        if (mine) {
          responseIdRef.current = mine.id;
          setResponseId(mine.id);
          // An existing response is HISTORY; the student starts this live
          // session as 未发言 and appends new rounds to the same thread.
          setStatus('not_started');
          const dialogue = await api.getDialogue(mine.id);
          const studentTurns = dialogue.filter(x => x.role === 'student');
          setTurnCount(studentTurns.length);
        }
      } catch (e) {
        console.error('StudentWindow bootstrap failed:', e);
      }
    })();
    return () => { cancelled = true; };
  }, [studentId]);

  // ── Mirror status from the live bus (teacher/other windows) ──
  useEffect(() => {
    if (!courseId) return;
    const unsubscribe = subscribeStatus(courseId, (evt) => {
      if (evt.type === 'teacher_question' && evt.responseId === responseIdRef.current) {
        setLastTeacherQuestion(evt.question || '');
        return;
      }
      if (evt.responseId === responseIdRef.current && evt.status) {
        setStatus(evt.status);
      }
    });
    return unsubscribe;
  }, [courseId]);

  // ── Poll dialogue so the adopted teacher question / round count stay fresh ──
  useEffect(() => {
    if (!courseId || !responseId) return;
    const timer = setInterval(async () => {
      try {
        const dialogue = await api.getDialogue(responseId);
        const studentTurns = dialogue.filter(x => x.role === 'student');
        setTurnCount(studentTurns.length);
      } catch { /* ignore polling errors */ }
    }, 3000);
    return () => clearInterval(timer);
  }, [courseId, responseId]);

  const publish = (s, response, round) => {
    setStatus(s);
    publishStatus(courseId, {
      responseId: responseIdRef.current,
      status: s,
      studentId: Number(studentId),
      response: response || null,
      round: round || undefined,
    });
  };

  const submitTranscript = async (text) => {
    if (!text.trim() || !courseId || !topicId) return null;
    setBusy(true);
    try {
      if (responseIdRef.current) {
        const updated = await api.appendTurn(responseIdRef.current, { role: 'student', content: text.trim(), turn_type: '' });
        responseIdRef.current = updated.id;
        setResponseId(updated.id);
        const newCount = (turnCount || 0) + 1;
        setTurnCount(newCount);
        publish('submitted', updated, newCount);
      } else {
        const updated = await api.importText(courseId, Number(studentId), topicId, text.trim(), 'student_device');
        responseIdRef.current = updated.id;
        setResponseId(updated.id);
        publish('submitted', updated, 1);
      }
      setTranscript('');
      return responseIdRef.current;
    } catch (e) {
      console.error('submit failed:', e);
      return null;
    } finally {
      setBusy(false);
    }
  };

  // ── Recording ───────────────────────────────────────────
  const startRecording = async () => {
    if (recording) return;
    const canRecord = typeof navigator !== 'undefined'
      && navigator.mediaDevices?.getUserMedia
      && typeof MediaRecorder !== 'undefined';

    if (!canRecord) {
      // Simulated recording fallback (demo-friendly).
      setRecording(true);
      setSimNote('（模拟录音中…）');
      for (let i = 3; i >= 0; i--) {
        setSimCountdown(i);
        await new Promise(r => setTimeout(r, 700));
      }
      setSimCountdown(0);
      setRecording(false);
      setSimNote(IS_DEMO ? '（演示环境：使用模拟转写文本）' : '（未获得麦克风权限，请改用粘贴文本）');
      await submitTranscript(DEMO_TRANSCRIPT);
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        setRecording(false);
        if (IS_DEMO) {
          setSimNote('（演示环境：录音已采集，转写内容为模拟）');
          await submitTranscript(DEMO_TRANSCRIPT);
        } else {
          setSimNote('（正在转写语音…）');
          try {
            const resp = await api.importAudio(courseId, Number(studentId), topicId, blob, 'student_device');
            responseIdRef.current = resp.id;
            setResponseId(resp.id);
            setTurnCount(1);
            publish('submitted', resp, 1);
          } catch (e) {
            console.error('audio import failed:', e);
            setSimNote('（语音转写失败，请改用粘贴文本）');
          }
        }
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecording(true);
      setSimNote('（正在录音…请口述你的回答）');
      publish('recording');
    } catch (e) {
      console.warn('mic denied:', e);
      setSimNote('（麦克风权限被拒，请改用粘贴文本）');
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    } else if (recording) {
      // simulated recording already finished by timer; nothing to do
    }
  };

  const handleStop = () => {
    if (recording) stopRecording();
  };

  const roundText = turnCount >= 3 ? '（已达 3 轮上限）' : `第 ${turnCount + 1} 轮`;

  return (
    <div className="min-h-screen bg-gradient-to-b from-indigo-50 to-white flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-lg overflow-hidden">
        {/* Header */}
        <div className="bg-indigo-600 text-white px-5 py-4">
          <div className="text-xs opacity-80">AI 伴学 · 随堂口述练习</div>
          <div className="text-xl font-bold mt-0.5">
            {student ? `${student.name}（${student.grade} 年级）` : '加载中…'}
          </div>
          <div className="mt-2 inline-block rounded-full px-3 py-1 text-xs font-medium bg-white/20">
            {STATUS_TEXT[status] || status}
          </div>
        </div>

        <div className="p-5 space-y-4">
          {/* Story / question */}
          <div className="rounded-xl bg-slate-50 border border-slate-200 p-4">
            <div className="text-xs text-slate-400 mb-1">思辨题目</div>
            <div className="text-sm font-semibold text-slate-800">{topic?.title || '加载题目中…'}</div>
            {topic?.stimulus_material && (
              <div className="text-sm text-slate-600 mt-2 leading-relaxed">{topic.stimulus_material}</div>
            )}
          </div>

          {/* Teacher question (multi-round) */}
          {lastTeacherQuestion && (
            <div className="rounded-xl bg-amber-50 border border-amber-200 p-4">
              <div className="text-xs text-amber-500 mb-1">老师追问</div>
              <div className="text-sm text-amber-900">{lastTeacherQuestion}</div>
            </div>
          )}

          {/* Recording controls */}
          <div className="text-center">
            {!recording ? (
              <button
                onClick={startRecording}
                disabled={busy || status === 'processing'}
                className="w-36 h-36 rounded-full bg-indigo-600 text-white text-lg font-bold shadow-lg hover:bg-indigo-700 active:scale-95 transition-transform disabled:opacity-40"
              >
                <div className="text-4xl mb-1">🎙️</div>
                开麦口述
              </button>
            ) : (
              <div className="flex flex-col items-center">
                <button
                  onClick={handleStop}
                  className="w-36 h-36 rounded-full bg-red-500 text-white text-lg font-bold shadow-lg animate-pulse hover:bg-red-600 active:scale-95 transition-transform"
                >
                  <div className="text-4xl mb-1">⏹️</div>
                  停止
                </button>
                <div className="text-xs text-red-500 mt-2">
                  {simCountdown > 0 ? `${simCountdown}…` : '正在录音'}
                </div>
              </div>
            )}
            <div className="text-xs text-slate-400 mt-2">{roundText}{simNote && ` · ${simNote}`}</div>
          </div>

          {/* Paste fallback */}
          <div className="rounded-xl border border-slate-200 p-3">
            <textarea
              value={pasteText}
              onChange={e => setPasteText(e.target.value)}
              rows={3}
              placeholder="也可以在这里输入/粘贴你的回答（兜底）"
              className="w-full text-sm border border-slate-200 rounded-lg p-2 outline-none focus:ring-1 focus:ring-indigo-300"
            />
            <button
              onClick={() => submitTranscript(pasteText)}
              disabled={busy || !pasteText.trim()}
              className="mt-2 w-full text-sm font-medium bg-indigo-100 text-indigo-700 rounded-lg py-2 hover:bg-indigo-200 disabled:opacity-40"
            >
              {busy ? '提交中…' : '提交回答'}
            </button>
          </div>

          <div className="text-[11px] text-slate-400 text-center">
            {IS_DEMO ? '演示模式：学生窗口为占位实现，用于讲通"口述→状态→评估"流程' : '口述内容将由 AI 语音识别转为文字'}
          </div>
        </div>
      </div>
    </div>
  );
}
