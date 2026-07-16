/**
 * Demo API client — returns data from embedded JSON, no backend needed.
 * Used when VITE_DEMO_MODE=true (e.g. GitHub Pages deployment).
 *
 * Key: demo-data.json is exported directly from SQLite, where JSON fields
 * are stored as TEXT strings. The backend normally parses these via Pydantic,
 * so we must parse them here before returning to the frontend.
 */
import demoData from '../demo-data.json';

const _data = demoData;
const ok = (d) => Promise.resolve(d);

// ── JSON field parsers ──────────────────────────────────

function _jp(val) {
  if (!val) return val;
  if (typeof val !== 'string') return val;
  try { return JSON.parse(val); } catch { return val; }
}

function _parseResponse(r) {
  if (!r) return r;
  return {
    ...r,
    ai_dimension_scores: _jp(r.ai_dimension_scores),
    teacher_dimension_scores: _jp(r.teacher_dimension_scores),
    ai_reasoning: _jp(r.ai_reasoning),
    ai_extracted_features: _jp(r.ai_extracted_features),
    ai_suggested_tags: _jp(r.ai_suggested_tags),
    teacher_tags: _jp(r.teacher_tags),
  };
}

function _parseTopic(t) {
  if (!t) return t;
  return { ...t, reference_arguments: _jp(t.reference_arguments) };
}

function _parseCalibration(c) {
  if (!c) return c;
  return {
    ...c,
    ai_original_scores: _jp(c.ai_original_scores),
    teacher_final_scores: _jp(c.teacher_final_scores),
    modifications: _jp(c.modifications),
  };
}

function _parseTag(t) {
  if (!t) return t;
  return { ...t, topic_ids: _jp(t.topic_ids) };
}

// ── Courses ─────────────────────────────────────────────
export const getCourses = () => ok(_data.courses);
export const getCourse = (cid) => ok(_data.courses.find(c => c.id === cid));

// ── Topics ──────────────────────────────────────────────
export const getTopics = (cid) =>
  ok(_data.topics.filter(t => t.course_id === cid).map(_parseTopic));

// ── Students ────────────────────────────────────────────
export const getStudents = (cid) => ok(_data.students.filter(s => s.course_id === cid));

// ── Responses ───────────────────────────────────────────
export const getResponses = (cid, studentId) => {
  let resps = _data.responses.map(_parseResponse);
  if (studentId) resps = resps.filter(r => r.student_id === studentId);
  return ok(resps);
};

export const getResponse = (rid) =>
  ok(_parseResponse(_data.responses.find(r => r.id === rid)));

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
  const responses = _data.responses.map(_parseResponse);

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
export const getTags = (cid) =>
  ok(_data.tags.filter(t => t.course_id === cid).map(_parseTag));
export const createTag = (cid, name, source) => ok({ id: 999, name, source, use_count: 0 });
export const updateTag = (tid, data) => ok({ id: tid, ...data });
export const mergeTags = (keepId, mergeIds) => ok({ id: keepId });
export const deleteTag = (tid) => ok({ ok: true });

// ── Calibrations ────────────────────────────────────────
export const getCalibrations = (cid) =>
  ok((_data.calibrations || []).map(_parseCalibration));
