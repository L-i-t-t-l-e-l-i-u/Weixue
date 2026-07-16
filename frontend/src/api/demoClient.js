/**
 * Demo API client — returns data from embedded JSON, no backend needed.
 * Used when VITE_DEMO_MODE=true (e.g. GitHub Pages deployment).
 */
import demoData from '../demo-data.json';

const _data = demoData;
const ok = (d) => Promise.resolve(d);

// ── Courses ─────────────────────────────────────────────
export const getCourses = () => ok(_data.courses);
export const getCourse = (cid) => ok(_data.courses.find(c => c.id === cid));

// ── Topics ──────────────────────────────────────────────
export const getTopics = (cid) => ok(_data.topics.filter(t => t.course_id === cid));

// ── Students ────────────────────────────────────────────
export const getStudents = (cid) => ok(_data.students.filter(s => s.course_id === cid));

// ── Responses ───────────────────────────────────────────
export const getResponses = (cid, studentId) => {
  let resps = _data.responses;
  if (studentId) resps = resps.filter(r => r.student_id === studentId);
  return ok(resps);
};

export const getResponse = (rid) => ok(_data.responses.find(r => r.id === rid));

export const reviewResponse = (rid, data) => ok({ ok: true });

// ── Assessment (no-op in demo) ──────────────────────────
export const assessCourse = (cid) => ok({ assessed: 0, skipped: 0 });
export const getAssessmentProgress = (cid) =>
  ok({ total: _data.responses.length, assessed: _data.responses.length, pending: 0 });
export const resetCourse = (cid) => ok({ ok: true });

// ── Comments ────────────────────────────────────────────
export const generateComment = (cid, studentId) => {
  const s = _data.students.find(s => s.id === studentId);
  return ok({ student_id: studentId, draft: s?.comment_draft || '' });
};
export const saveCommentDraft = (cid, studentId, draft) => ok({ ok: true });
export const batchGenerateComments = (cid) => ok({ results: [] });

// ── Prep Analytics (simplified) ─────────────────────────
export const getPrepAnalytics = (cid) => ok([]);

// ── Report (simplified) ─────────────────────────────────
export const getClassReport = (cid) => {
  const ratingMap = { A: 4, 'A+': 4, 'B+': 3.5, B: 3, 'C+': 2.5, C: 2, D: 1 };
  const students = _data.students;
  const responses = _data.responses;

  const studentStats = students.map(st => {
    const vals = [];
    responses.filter(r => r.student_id === st.id).forEach(r => {
      const scores = r.teacher_dimension_scores || r.ai_dimension_scores;
      if (scores && typeof scores === 'object') {
        Object.values(scores).forEach(rating => {
          vals.push(ratingMap[rating] || 2);
        });
      }
    });
    return {
      student_id: st.id, name: st.name, grade: st.grade,
      avg_score: vals.length ? Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 100) / 100 : 0,
      uncertain: 0,
    };
  });

  const avgs = studentStats.map(s => s.avg_score).filter(a => a > 0);
  return ok({
    class_avg: avgs.length ? Math.round((avgs.reduce((a, b) => a + b, 0) / avgs.length) * 100) / 100 : 0,
    student_count: students.length,
    topic_stats: [],
    student_stats: studentStats,
    top_tags: _data.tags.slice(0, 10).map(t => ({ name: t.name, count: t.use_count, source: t.source })),
  });
};

// ── Tags ────────────────────────────────────────────────
export const getTags = (cid) => ok(_data.tags.filter(t => t.course_id === cid));
export const createTag = (cid, name, source) => ok({ id: 999, name, source, use_count: 0 });
export const updateTag = (tid, data) => ok({ id: tid, ...data });
export const mergeTags = (keepId, mergeIds) => ok({ id: keepId });
export const deleteTag = (tid) => ok({ ok: true });

// ── Calibrations ────────────────────────────────────────
export const getCalibrations = (cid) => ok(_data.calibrations || []);
