/**
 * Pure analytics computations shared by the workbench pages (备课/学情报告)
 * and the demo client. Everything derives from the SAME response objects the
 * classroom mode uses, so 课堂模式 and 工作台 can never diverge.
 */
import { ratingToNumber } from './ratings';

export function computePrepAnalytics(students, topics, responses) {
  const studentIds = new Set(students.map(student => student.id));
  const studentNames = new Map(students.map(student => [student.id, student.name]));

  const result = topics.map(topic => {
    const dimensionValues = {};
    const lowStudents = [];
    const tagCounts = {};

    responses
      .filter(response => response.student_id !== undefined && studentIds.has(response.student_id))
      .filter(response => response.topic_id === topic.id)
      .forEach(response => {
        const scores = response.teacher_dimension_scores || response.ai_dimension_scores;
        const confidence = response.teacher_confidence_override || response.ai_confidence;
        if (confidence === 'uncertain' && !response.teacher_dimension_scores) return;

        const studentValues = [];
        if (scores && typeof scores === 'object') {
          Object.entries(scores).forEach(([dimension, rating]) => {
            const value = ratingToNumber(rating);
            if (value === null) return;
            (dimensionValues[dimension] ||= []).push(value);
            studentValues.push(value);
          });
        }
        if (studentValues.length > 0) {
          const average = studentValues.reduce((sum, value) => sum + value, 0) / studentValues.length;
          if (average < 2.5) lowStudents.push(`${studentNames.get(response.student_id)}(${average.toFixed(1)})`);
        }

        const tags = response.teacher_tags || response.ai_suggested_tags || [];
        tags.forEach(tag => { tagCounts[tag] = (tagCounts[tag] || 0) + 1; });
      });

    const avgDimensionScores = Object.fromEntries(
      Object.entries(dimensionValues).map(([dimension, values]) => [
        dimension,
        Math.round((values.reduce((sum, value) => sum + value, 0) / values.length) * 100) / 100,
      ]),
    );
    return {
      topic_id: topic.id,
      title: topic.title,
      topic_type: topic.topic_type,
      cognitive_tier: topic.cognitive_tier,
      avg_dimension_scores: avgDimensionScores,
      weak_dimensions: Object.entries(avgDimensionScores)
        .filter(([, average]) => average < 2.5)
        .map(([dimension]) => dimension),
      low_students: lowStudents,
      error_tags: Object.entries(tagCounts)
        .sort((a, b) => b[1] - a[1])
        .map(([tag, count]) => ({ tag, count })),
    };
  });

  result.sort((a, b) => {
    const aMin = Math.min(...Object.values(a.avg_dimension_scores), 5);
    const bMin = Math.min(...Object.values(b.avg_dimension_scores), 5);
    return aMin - bMin;
  });
  return result;
}

export function computeClassReport(students, topics, responses, tags, courseId) {
  const studentIds = new Set(students.map(student => student.id));
  const inCourse = responses.filter(response =>
    response.student_id !== undefined && studentIds.has(response.student_id));

  const topicStats = topics.map(topic => {
    const dimensionValues = {};
    let uncertain = 0;
    inCourse.filter(response => response.topic_id === topic.id).forEach(response => {
      const scores = response.teacher_dimension_scores || response.ai_dimension_scores;
      const confidence = response.teacher_confidence_override || response.ai_confidence;
      if (confidence === 'uncertain' && !response.teacher_dimension_scores) {
        uncertain += 1;
        return;
      }
      if (!scores || typeof scores !== 'object') return;
      Object.entries(scores).forEach(([dimension, rating]) => {
        const value = ratingToNumber(rating);
        if (value !== null) (dimensionValues[dimension] ||= []).push(value);
      });
    });
    return {
      topic_id: topic.id,
      title: topic.title,
      cognitive_tier: topic.cognitive_tier,
      avg_dimension_scores: Object.fromEntries(
        Object.entries(dimensionValues).map(([dimension, values]) => [
          dimension,
          Math.round((values.reduce((sum, value) => sum + value, 0) / values.length) * 100) / 100,
        ]),
      ),
      uncertain,
    };
  });

  const studentStats = students.map(st => {
    const vals = [];
    let uncertain = 0;
    inCourse.filter(r => r.student_id === st.id).forEach(r => {
      const scores = r.teacher_dimension_scores || r.ai_dimension_scores;
      const confidence = r.teacher_confidence_override || r.ai_confidence;
      if (confidence === 'uncertain' && !r.teacher_dimension_scores) {
        uncertain += 1;
        return;
      }
      if (scores && typeof scores === 'object') {
        Object.values(scores).forEach(rating => {
          const value = ratingToNumber(rating);
          if (value !== null) vals.push(value);
        });
      }
    });
    return {
      student_id: st.id, name: st.name, grade: st.grade,
      cognitive_tier: st.grade <= 2 ? 'basic' : st.grade <= 5 ? 'developing' : 'advancing',
      avg_score: vals.length ? Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 100) / 100 : 0,
      uncertain,
    };
  });

  const avgs = studentStats.map(s => s.avg_score).filter(a => a > 0);
  return {
    class_avg: avgs.length ? Math.round((avgs.reduce((a, b) => a + b, 0) / avgs.length) * 100) / 100 : 0,
    student_count: students.length,
    topic_stats: topicStats,
    student_stats: studentStats,
    top_tags: (tags || [])
      .filter(tag => tag.course_id === courseId && tag.use_count > 0)
      .sort((a, b) => b.use_count - a.use_count)
      .slice(0, 10)
      .map(tag => ({ name: tag.name, count: tag.use_count, source: tag.source })),
  };
}
