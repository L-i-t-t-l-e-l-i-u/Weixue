/**
 * API client — automatically switches to demo mode when VITE_DEMO_MODE=true.
 * Demo mode uses embedded data (no backend needed, suitable for GitHub Pages).
 */
import axios from 'axios';
import * as _demo from './demoClient';

const _isDemo = import.meta.env.VITE_DEMO_MODE === 'true';
const api = axios.create({ baseURL: '/api' });

// ── Courses ─────────────────────────────────────────────
export const getCourses = (...a) => _isDemo ? _demo.getCourses(...a) : api.get('/courses').then(r => r.data);
export const getCourse = (...a) => _isDemo ? _demo.getCourse(...a) : api.get(`/courses/${a[0]}`).then(r => r.data);

// ── Topics ──────────────────────────────────────────────
export const getTopics = (...a) => _isDemo ? _demo.getTopics(...a) : api.get(`/courses/${a[0]}/topics`).then(r => r.data);

// ── Students ────────────────────────────────────────────
export const getStudents = (...a) => _isDemo ? _demo.getStudents(...a) : api.get(`/courses/${a[0]}/students`).then(r => r.data);

// ── Responses ───────────────────────────────────────────
export const getResponses = (...a) => _isDemo ? _demo.getResponses(...a) :
  api.get(`/courses/${a[0]}/responses`, { params: a[1] ? { student_id: a[1] } : {} }).then(r => r.data);
export const getResponse = (...a) => _isDemo ? _demo.getResponse(...a) : api.get(`/responses/${a[0]}`).then(r => r.data);
export const reviewResponse = (...a) => _isDemo ? _demo.reviewResponse(...a) :
  api.post(`/responses/${a[0]}/review`, a[1]).then(r => r.data);

// ── Assessment ──────────────────────────────────────────
export const assessCourse = (...a) => _isDemo ? _demo.assessCourse(...a) : api.post(`/courses/${a[0]}/assess`).then(r => r.data);
export const getAssessmentProgress = (...a) => _isDemo ? _demo.getAssessmentProgress(...a) :
  api.get(`/courses/${a[0]}/assessment-progress`).then(r => r.data);
export const resetCourse = (...a) => _isDemo ? _demo.resetCourse(...a) : api.post(`/courses/${a[0]}/reset`).then(r => r.data);

// ── Comments ────────────────────────────────────────────
export const generateComment = (...a) => _isDemo ? _demo.generateComment(...a) :
  api.post(`/courses/${a[0]}/comments`, { student_id: a[1] }).then(r => r.data);
export const saveCommentDraft = (...a) => _isDemo ? _demo.saveCommentDraft(...a) :
  api.post(`/courses/${a[0]}/comments/save`, { student_id: a[1], draft: a[2] }).then(r => r.data);
export const batchGenerateComments = (...a) => _isDemo ? _demo.batchGenerateComments(...a) :
  api.post(`/courses/${a[0]}/comments/batch`).then(r => r.data);

// ── Prep Analytics ──────────────────────────────────────
export const getPrepAnalytics = (...a) => _isDemo ? _demo.getPrepAnalytics(...a) :
  api.get(`/courses/${a[0]}/prep`).then(r => r.data);

// ── Report ──────────────────────────────────────────────
export const getClassReport = (...a) => _isDemo ? _demo.getClassReport(...a) :
  api.get(`/courses/${a[0]}/report`).then(r => r.data);

// ── Tags ────────────────────────────────────────────────
export const getTags = (...a) => _isDemo ? _demo.getTags(...a) : api.get(`/courses/${a[0]}/tags`).then(r => r.data);
export const createTag = (...a) => _isDemo ? _demo.createTag(...a) :
  api.post(`/courses/${a[0]}/tags`, null, { params: { name: a[1], source: a[2] || 'base' } }).then(r => r.data);
export const updateTag = (...a) => _isDemo ? _demo.updateTag(...a) : api.put(`/tags/${a[0]}`, a[1]).then(r => r.data);
export const mergeTags = (...a) => _isDemo ? _demo.mergeTags(...a) :
  api.post('/tags/merge', { keep_id: a[0], merge_ids: a[1] }).then(r => r.data);
export const deleteTag = (...a) => _isDemo ? _demo.deleteTag(...a) : api.delete(`/tags/${a[0]}`).then(r => r.data);

// ── Calibrations ────────────────────────────────────────
export const getCalibrations = (...a) => _isDemo ? _demo.getCalibrations(...a) :
  api.get(`/courses/${a[0]}/calibrations`).then(r => r.data);

export default api;
