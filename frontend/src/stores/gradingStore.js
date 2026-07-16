import { create } from 'zustand';
import * as api from '../api/client';

const useStore = create((set, get) => ({
  // ── State ──────────────────────────────────────────────────
  courseId: null,
  course: null,
  topics: [],
  students: [],
  responses: {},        // { [studentId]: [response, ...] }
  tags: [],
  currentStudentIdx: 0,
  currentTab: 'grading',
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
    } catch (e) {
      console.error('Failed to load course:', e);
      set({ loading: false });
    }
  },

  loadAllCourses: async () => {
    const list = await api.getCourses();
    if (list.length > 0 && !get().courseId) {
      await get().loadCourse(list[0].id);
    }
    return list;
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
      await get().loadCourse(cid);
    } catch (e) {
      console.error('Reset failed:', e);
    }
  },
}));

export default useStore;
