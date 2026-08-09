import { create } from 'zustand';
import * as api from '../api/client';
import { subscribeStatus, publishStatus } from '../utils/statusBus';

let _liveSubscribedCid = null;
let _liveUnsubscribe = null;

const useStore = create((set, get) => ({
  // ── State ──────────────────────────────────────────────────
  courseId: null,
  course: null,
  courses: [],
  topics: [],
  students: [],
  responses: {},        // { [studentId]: [response, ...] }
  tags: [],
  currentStudentIdx: 0,
  currentTab: 'grading',
  currentMode: 'live',          // 'live' (课堂) / 'workbench' (工作台)
  liveTopicId: null,
  liveStatus: {},               // { [responseId]: 'not_started'|'recording'|'submitted'|'processing'|'processed' }
  liveDialogue: {},             // { [responseId]: [turn, ...] }
  liveSuggestions: {},          // { [responseId]: {questions, scaffold_status, echo_risk, note} }
  liveRounds: {},               // { [responseId]: student-round count }
  liveAdopted: {},              // { [responseId]: adopted teacher question }
  liveBusy: {},                 // { [responseId]: true } while an action is in flight
  loading: false,
  assessing: false,     // was "grading"
  assessmentProgress: null,

  // ── Derived ────────────────────────────────────────────────
  currentStudent: () => {
    const { students, currentStudentIdx } = get();
    return students[currentStudentIdx] || null;
  },

  studentResponses: (studentId) => {
    return get().responses[studentId] || [];
  },

  findResponse: (responseId) => {
    const { responses } = get();
    let target = null;
    Object.values(responses).flat().forEach(r => { if (r.id === responseId) target = r; });
    return target;
  },

  // ── Actions ────────────────────────────────────────────────
  setTab: (tab) => set({ currentTab: tab }),
  setStudentIdx: (idx) => set({ currentStudentIdx: idx }),

  loadCourse: async (cid) => {
    set({ loading: true });
    try {
      const [course, topics, students, tags] = await Promise.all([
        api.getCourse(cid),
        api.getTopics(cid),
        api.getStudents(cid),
        api.getTags(cid),
      ]);
      // Load all responses
      const resps = await api.getResponses(cid);
      const respMap = {};
      resps.forEach(r => {
        if (!respMap[r.student_id]) respMap[r.student_id] = [];
        respMap[r.student_id].push(r);
      });
      set({ course, topics, students, tags, responses: respMap, courseId: cid, loading: false });
      get().initLiveStatus();
    } catch (e) {
      console.error('Failed to load course:', e);
      set({ loading: false });
    }
  },

  loadAllCourses: async () => {
    const list = await api.getCourses();
    set({ courses: list });
    if (list.length > 0 && !get().courseId) {
      await get().loadCourse(list[0].id);
    }
    return list;
  },

  selectCourse: async (cid) => {
    if (cid === get().courseId) return;
    set({ courseId: cid, currentStudentIdx: 0 });
    await get().loadCourse(cid);
  },

  createCourse: async (data) => {
    const c = await api.createCourse(data);
    const list = await api.getCourses();
    set({ courses: list });
    await get().selectCourse(c.id);
    return c;
  },

  runAssessment: async () => {
    const cid = get().courseId;
    if (!cid) return;
    set({ assessing: true, assessmentProgress: null });

    try {
      await api.assessCourse(cid);
    } catch (e) {
      if (e.response?.status === 409) {
        console.warn('Assessment already in progress');
      } else {
        console.error('Failed to start assessment:', e);
        set({ assessing: false });
        return;
      }
    }

    // Poll progress every 500ms
    const pollInterval = setInterval(async () => {
      try {
        const p = await api.getAssessmentProgress(cid);
        set({ assessmentProgress: p });

        if (!p.active) {
          clearInterval(pollInterval);
          // Reload responses after assessment completes
          const resps = await api.getResponses(cid);
          const respMap = {};
          resps.forEach(r => {
            if (!respMap[r.student_id]) respMap[r.student_id] = [];
            respMap[r.student_id].push(r);
          });
          set({ responses: respMap, assessing: false });
        }
      } catch (e) {
        console.error('Progress poll failed:', e);
      }
    }, 500);
  },

  submitReview: async (responseId, data) => {
    const updated = await api.reviewResponse(responseId, data);
    // Update local state
    const { responses } = get();
    const newResps = { ...responses };
    for (const sid of Object.keys(newResps)) {
      newResps[sid] = newResps[sid].map(r => r.id === responseId ? updated : r);
    }
    set({ responses: newResps });
    return updated;
  },

  refreshTags: async () => {
    const cid = get().courseId;
    if (!cid) return;
    const tags = await api.getTags(cid);
    set({ tags });
  },

  resetAll: async () => {
    const cid = get().courseId;
    if (!cid) return;
    try {
      await api.resetCourse(cid);
      set({
        liveStatus: {}, liveDialogue: {}, liveSuggestions: {},
        liveRounds: {}, liveAdopted: {}, liveBusy: {},
      });
      await get().loadCourse(cid);
    } catch (e) {
      console.error('Reset failed:', e);
    }
  },

  // ── Live classroom mode ─────────────────────────────────
  setMode: (mode) => set({ currentMode: mode }),
  setLiveTopic: (topicId) => set({ liveTopicId: topicId }),

  initLiveStatus: () => {
    // liveStatus only tracks the CURRENT live session. Pre-existing historical
    // responses must NOT pre-fill it, otherwise the classroom would show
    // "已处理" for students who have not spoken in this session. Entries for
    // responses that no longer exist are dropped.
    const { responses, topics } = get();
    const validIds = new Set(Object.values(responses).flat().map(r => r.id));
    set(state => {
      const kept = {};
      Object.entries(state.liveStatus).forEach(([rid, s]) => {
        if (validIds.has(Number(rid))) kept[rid] = s;
      });
      return {
        liveStatus: kept,
        liveTopicId: get().liveTopicId || topics[0]?.id || null,
      };
    });
  },

  refreshResponses: async (cid) => {
    const resps = await api.getResponses(cid);
    const respMap = {};
    resps.forEach(r => {
      if (!respMap[r.student_id]) respMap[r.student_id] = [];
      respMap[r.student_id].push(r);
    });
    set({ responses: respMap, courseId: cid });
    get().initLiveStatus();
    return respMap;
  },

  subscribeLiveStatus: (cid) => {
    if (_liveSubscribedCid === cid) return;
    if (_liveUnsubscribe) { _liveUnsubscribe(); _liveUnsubscribe = null; }
    _liveSubscribedCid = cid;
    _liveUnsubscribe = subscribeStatus(cid, (evt) => {
      if (evt.response) {
        get()._upsertResponse(evt.response);
      }
      if (!evt.responseId) return;
      if (evt.type === 'teacher_question') {
        set(state => ({ liveAdopted: { ...state.liveAdopted, [evt.responseId]: evt.question || '' } }));
        return;
      }
      const prevRound = get().liveRounds[evt.responseId] || 0;
      const nextRound = evt.round || prevRound;
      set(state => ({
        liveStatus: { ...state.liveStatus, [evt.responseId]: evt.status },
        liveRounds: { ...state.liveRounds, [evt.responseId]: Math.max(prevRound, nextRound) },
      }));
      if (nextRound > prevRound) {
        set(state => ({ liveAdopted: { ...state.liveAdopted, [evt.responseId]: '' } }));
      }
      if (evt.status === 'submitted') {
        // Auto-generate scaffolding suggestions when a new answer arrives.
        setTimeout(() => {
          get().loadDialogue(evt.responseId);
          const r = get().findResponse(evt.responseId);
          if (r) get().suggestTurnFor(r.id);
        }, 250);
      }
    });
  },

  setLiveStatus: async (responseId, status, response) => {
    set(state => ({ liveStatus: { ...state.liveStatus, [responseId]: status } }));
    const cid = get().courseId;
    if (response) get()._upsertResponse(response);
    publishStatus(cid, { responseId, status, response: response || null });
    try {
      await api.updateResponseStatus(responseId, status);
    } catch (e) {
      console.warn('updateResponseStatus failed (demo fallback ok):', e);
    }
  },

  loadDialogue: async (responseId) => {
    try {
      const turns = await api.getDialogue(responseId);
      set(state => ({ liveDialogue: { ...state.liveDialogue, [responseId]: turns } }));
      return turns;
    } catch (e) {
      console.warn('loadDialogue failed:', e);
      return [];
    }
  },

  suggestTurnFor: async (responseId) => {
    set(state => ({ liveBusy: { ...state.liveBusy, [responseId]: true } }));
    try {
      const suggestion = await api.suggestTurn(responseId);
      set(state => ({ liveSuggestions: { ...state.liveSuggestions, [responseId]: suggestion } }));
      return suggestion;
    } catch (e) {
      console.warn('suggestTurn failed:', e);
      return null;
    } finally {
      set(state => ({ liveBusy: { ...state.liveBusy, [responseId]: false } }));
    }
  },

  adoptSuggestion: async (responseId, question) => {
    try {
      const updated = await api.appendTurn(responseId, { role: 'teacher', content: question, turn_type: 'scaffold' });
      get()._upsertResponse(updated);
      set(state => ({ liveAdopted: { ...state.liveAdopted, [responseId]: question } }));
      publishStatus(get().courseId, {
        responseId, status: 'submitted', type: 'teacher_question', question,
      });
      await get().loadDialogue(responseId);
      return updated;
    } catch (e) {
      console.warn('adoptSuggestion failed:', e);
      return null;
    }
  },

  appendStudentTurn: async (responseId, content) => {
    try {
      const updated = await api.appendTurn(responseId, { role: 'student', content, turn_type: '' });
      get()._upsertResponse(updated);
      await get().setLiveStatus(responseId, 'submitted');
      await get().loadDialogue(responseId);
      return updated;
    } catch (e) {
      console.warn('appendStudentTurn failed:', e);
      return null;
    }
  },

  assessLive: async (responseId) => {
    set(state => ({ liveBusy: { ...state.liveBusy, [responseId]: true } }));
    await get().setLiveStatus(responseId, 'processing');
    try {
      const updated = await api.assessOne(responseId);
      get()._upsertResponse(updated);
      await get().setLiveStatus(responseId, 'processed', updated);
      await get().loadDialogue(responseId);
      return updated;
    } catch (e) {
      console.warn('assessOne failed:', e);
      await get().setLiveStatus(responseId, 'processed');
      return null;
    } finally {
      set(state => ({ liveBusy: { ...state.liveBusy, [responseId]: false } }));
    }
  },

  reviewLive: async (responseId, { rating, note }) => {
    const { responses } = get();
    let target = null;
    Object.values(responses).flat().forEach(r => { if (r.id === responseId) target = r; });
    if (!target) return null;
    const updated = await get().submitReview(responseId, {
      dimension_scores: target.teacher_dimension_scores || target.ai_dimension_scores || {},
      tags: target.teacher_tags || target.ai_suggested_tags || [],
      note: note || target.teacher_note || '',
      rating: rating || '',
    });
    await get().setLiveStatus(responseId, 'processed', updated);
    return updated;
  },

  openStudentWindow: (studentId) => {
    const { courseId, liveTopicId } = get();
    const url = `${window.location.pathname}#/student/${studentId}?course=${courseId || ''}&topic=${liveTopicId || ''}`;
    window.open(url, `student-${studentId}`, 'width=520,height=760');
  },

  _upsertResponse: (updated) => {
    api.registerDemoResponse(updated);
    const { responses } = get();
    const newResps = { ...responses };
    for (const sid of Object.keys(newResps)) {
      newResps[sid] = newResps[sid].map(r => (r.id === updated.id ? updated : r));
    }
    if (!Object.values(newResps).flat().some(r => r.id === updated.id)) {
      const list = newResps[updated.student_id] || [];
      newResps[updated.student_id] = [...list, updated];
    }
    // NOTE: do NOT auto-set liveStatus here. A response that exists in the data
    // layer but was not touched during this live session is HISTORY; the
    // classroom card stays 未发言 until a live event touches it.
    set({ responses: newResps });
  },
}));

export default useStore;
