/**
 * Single source of truth for the live-classroom status of a response.
 * Both 课堂模式 and 工作台 derive status from the same response object, so the
 * two modes can never disagree about a student's state.
 */
export function deriveResponseStatus(r) {
  if (!r) return 'not_started';
  if (r.processing_status && r.processing_status !== 'not_started') return r.processing_status;
  if (r.teacher_reviewed) return 'processed';
  if (r.raw_text && r.raw_text.trim()) return 'submitted';
  return 'not_started';
}
