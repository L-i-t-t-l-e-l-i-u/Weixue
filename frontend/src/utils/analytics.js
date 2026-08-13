/**
 * Pure analytics computations shared by the workbench pages (备课/学情报告)
 * and the demo client. Everything derives from the SAME response objects the
 * classroom mode uses, so 课堂模式 and 工作台 can never diverge.
 */
import {
  ratingToNumber, collectBonusFlags, normalizeScores,
  passLineForGrade, isPassing,
} from './ratings';

export const DIM_LABELS = {
  position: '立意', material: '选材', structure: '结构',
  language: '语言', perspective: '视角',
};

export function computePrepAnalytics(students, topics, responses) {
  const studentIds = new Set(students.map(student => student.id));
  const studentNames = new Map(students.map(student => [student.id, student.name]));
  const studentGrades = new Map(students.map(student => [student.id, student.grade]));

  const result = topics.map(topic => {
    const dimensionEntries = {};   // dim -> [{ value, grade }]
    const lowStudents = [];
    const tagCounts = {};

    responses
      .filter(response => response.student_id !== undefined && studentIds.has(response.student_id))
      .filter(response => response.topic_id === topic.id)
      .forEach(response => {
        const scores = normalizeScores(response.teacher_dimension_scores || response.ai_dimension_scores);
        const confidence = response.teacher_confidence_override || response.ai_confidence;
        if (confidence === 'uncertain' && !response.teacher_dimension_scores) return;

        const studentValues = [];
        if (scores && typeof scores === 'object') {
          Object.entries(scores).forEach(([dimension, rating]) => {
            const value = ratingToNumber(rating);
            if (value === null) return;
            (dimensionEntries[dimension] ||= []).push({
              value,
              grade: studentGrades.get(response.student_id),
            });
            studentValues.push(value);
          });
        }
        if (studentValues.length > 0) {
          const average = studentValues.reduce((sum, value) => sum + value, 0) / studentValues.length;
          // 合格线按学生自己的年级：低年级 ≥2.5，高年级 ≥3.0。
          if (!isPassing(studentGrades.get(response.student_id), average)) {
            lowStudents.push(`${studentNames.get(response.student_id)}(${average.toFixed(1)})`);
          }
        }

        const tags = response.teacher_tags || response.ai_suggested_tags || [];
        tags.forEach(tag => { tagCounts[tag] = (tagCounts[tag] || 0) + 1; });
      });

    const avgDimensionScores = Object.fromEntries(
      Object.entries(dimensionEntries).map(([dimension, entries]) => [
        dimension,
        Math.round((entries.reduce((sum, e) => sum + e.value, 0) / entries.length) * 100) / 100,
      ]),
    );
    return {
      topic_id: topic.id,
      title: topic.title,
      topic_type: topic.topic_type,
      cognitive_tier: topic.cognitive_tier,
      avg_dimension_scores: avgDimensionScores,
      weak_dimensions: Object.entries(dimensionEntries)
        .filter(([, entries]) => {
          if (entries.length === 0) return false;
          const below = entries.filter(e => !isPassing(e.grade, e.value)).length;
          return below / entries.length >= 0.4;
        })
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

/**
 * Deterministic prep insights — mirrors backend /api/courses/{cid}/prep/insights
 * so demo mode and real mode return the same shape.
 */
export function computePrepInsights(students, topics, responses, courseId) {
  const studentIds = new Set(students.map(s => s.id));
  const studentMap = new Map(students.map(s => [s.id, s]));
  const inCourse = responses.filter(r =>
    r.student_id !== undefined && studentIds.has(r.student_id));

  const respByTopic = {};
  inCourse.forEach(r => { (respByTopic[r.topic_id] ||= []).push(r); });
  const participation = {
    students_total: students.length,
    students_answered: new Set(inCourse.map(r => r.student_id)).size,
    responses_total: inCourse.length,
    per_topic: topics.map(t => {
      const list = respByTopic[t.id] || [];
      let passing = 0;
      const topicQuick = { good: 0, guide: 0, echo: 0 };
      list.forEach(r => {
        if (r.teacher_rating in topicQuick) topicQuick[r.teacher_rating] += 1;
        const scores = normalizeScores(r.teacher_dimension_scores || r.ai_dimension_scores);
        const confidence = r.teacher_confidence_override || r.ai_confidence;
        if (confidence === 'uncertain' && !r.teacher_dimension_scores) return;
        const vals = Object.values(scores || {}).map(ratingToNumber).filter(v => v !== null);
        const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
        if (vals.length && isPassing(studentMap.get(r.student_id)?.grade, avg)) passing += 1;
      });
      return {
        topic_id: t.id,
        title: t.title,
        responses: list.length,
        reviewed: list.filter(r => r.teacher_reviewed).length,
        passing,
        quick_ratings: topicQuick,
      };
    }),
  };

  // Tier summary + per-student averages (for class_avg)
  const tierRaw = {};
  const studentAvgs = [];
  const studentGrades = [];
  students.forEach(st => {
    const entry = (tierRaw[st.cognitive_tier] ||= { students: 0, scores: [], weak_students: 0 });
    entry.students += 1;
    const vals = [];
    inCourse.filter(r => r.student_id === st.id).forEach(r => {
      const scores = normalizeScores(r.teacher_dimension_scores || r.ai_dimension_scores);
      const confidence = r.teacher_confidence_override || r.ai_confidence;
      if (confidence === 'uncertain' && !r.teacher_dimension_scores) return;
      if (!scores || typeof scores !== 'object') return;
      Object.values(scores).forEach(rating => {
        const v = ratingToNumber(rating);
        if (v !== null) vals.push(v);
      });
    });
    const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
    if (vals.length && !isPassing(st.grade, avg)) entry.weak_students += 1;
    if (vals.length) {
      entry.scores.push(avg);
      studentAvgs.push(avg);
      studentGrades.push(st.grade);
    }
  });
  const tierSummary = Object.fromEntries(Object.entries(tierRaw).map(([tier, v]) => [
    tier,
    {
      students: v.students,
      avg_score: v.scores.length
        ? Math.round((v.scores.reduce((a, b) => a + b, 0) / v.scores.length) * 100) / 100
        : 0,
      weak_students: v.weak_students,
    },
  ]));
  participation.class_avg = studentAvgs.length
    ? Math.round((studentAvgs.reduce((a, b) => a + b, 0) / studentAvgs.length) * 100) / 100
    : 0;
  participation.pass_count = studentAvgs.filter((avg, i) =>
    isPassing(studentGrades[i], avg)).length;
  participation.pass_rate = studentAvgs.length
    ? Math.round((participation.pass_count / studentAvgs.length) * 100) / 100
    : 0;

  // Highlights: strong answers worth praising in class
  const candidates = [];
  inCourse.forEach(r => {
    const scores = normalizeScores(r.teacher_dimension_scores || r.ai_dimension_scores);
    const confidence = r.teacher_confidence_override || r.ai_confidence;
    if (confidence === 'uncertain' && !r.teacher_dimension_scores) return;
    if (!scores || typeof scores !== 'object') return;
    const vals = Object.values(scores).map(ratingToNumber).filter(v => v !== null);
    if (!vals.length) return;
    const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
    // 优质发言 = 高于该生年级合格线至少半档（1-3年级 ≥3.0，4-6年级 ≥3.5）。
    if (avg < passLineForGrade(student.grade) + 0.5) return;
    const topic = topics.find(t => t.id === r.topic_id);
    const student = studentMap.get(r.student_id);
    if (!topic || !student) return;
    candidates.push({
      topic_id: topic.id,
      topic_title: topic.title,
      student_id: student.id,
      student_name: student.name,
      grade: student.grade,
      text: (r.cleaned_text || r.raw_text || '').slice(0, 160),
      scores,
      avg: Math.round(avg * 100) / 100,
      bonus_flags: r.ai_bonus_flags || [],
      tags: (r.teacher_tags || r.ai_suggested_tags || []).slice(0, 4),
    });
  });
  candidates.sort((a, b) => b.avg - a.avg);
  const perTopicCount = {};
  const highlights = [];
  for (const h of candidates) {
    if ((perTopicCount[h.topic_id] || 0) >= 2) continue;
    perTopicCount[h.topic_id] = (perTopicCount[h.topic_id] || 0) + 1;
    highlights.push(h);
    if (highlights.length >= 6) break;
  }

  // Per-topic highlights (分题分析): ≤2 per topic, ≤12 total.
  const topicHighlights = [];
  const perTopicCount2 = {};
  for (const h of candidates) {
    if ((perTopicCount2[h.topic_id] || 0) >= 2) continue;
    perTopicCount2[h.topic_id] = (perTopicCount2[h.topic_id] || 0) + 1;
    topicHighlights.push(h);
    if (topicHighlights.length >= 12) break;
  }

  // Problem patterns: dimensions with students below their own grade pass line
  const dimStudents = {};
  const dimTopics = {};
  topics.forEach(t => students.forEach(st => {
    const r = inCourse.find(x => x.student_id === st.id && x.topic_id === t.id);
    if (!r) return;
    const scores = normalizeScores(r.teacher_dimension_scores || r.ai_dimension_scores);
    const confidence = r.teacher_confidence_override || r.ai_confidence;
    if (confidence === 'uncertain' && !r.teacher_dimension_scores) return;
    if (!scores || typeof scores !== 'object') return;
    Object.entries(scores).forEach(([dim, rating]) => {
      const v = ratingToNumber(rating);
      if (v === null || isPassing(st.grade, v)) return;
      (dimStudents[dim] ||= new Set()).add(st.id);
      (dimTopics[dim] ||= new Set()).add(t.id);
    });
  }));
  const problemPatterns = Object.entries(dimStudents)
    .map(([dim, set]) => ({
      dimension: dim,
      label: DIM_LABELS[dim] || dim,
      students_affected: set.size,
      topics_affected: (dimTopics[dim] || new Set()).size,
    }))
    .sort((a, b) => b.students_affected - a.students_affected);

  // Top tags across the class
  const tagCounts = {};
  inCourse.forEach(r =>
    (r.teacher_tags || r.ai_suggested_tags || []).forEach(tag => {
      tagCounts[tag] = (tagCounts[tag] || 0) + 1;
    }),
  );
  const topTags = Object.entries(tagCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([tag, count]) => ({ tag, count }));

  // 课堂即时评级（教师第一印象，绿/黄/红三档）——与五维度评分互补。
  const quickRatingCounts = { good: 0, guide: 0, echo: 0 };
  inCourse.forEach(r => {
    if (r.teacher_rating in quickRatingCounts) quickRatingCounts[r.teacher_rating] += 1;
  });

  return {
    course_id: courseId,
    participation,
    tier_summary: tierSummary,
    highlights,
    topic_highlights: topicHighlights,
    problem_patterns: problemPatterns,
    top_tags: topTags,
    quick_rating_counts: quickRatingCounts,
  };
}

export function computeClassReport(students, topics, responses, tags, courseId) {
  const studentIds = new Set(students.map(student => student.id));
  const inCourse = responses.filter(response =>
    response.student_id !== undefined && studentIds.has(response.student_id));

  // Class-level dimension averages (radar chart) — same aggregation as the
  // backend /report, so demo and real mode can never diverge.
  const classDims = {};
  inCourse.forEach(response => {
    const scores = normalizeScores(response.teacher_dimension_scores || response.ai_dimension_scores);
    const confidence = response.teacher_confidence_override || response.ai_confidence;
    if (confidence === 'uncertain' && !response.teacher_dimension_scores) return;
    if (!scores || typeof scores !== 'object') return;
    Object.entries(scores).forEach(([dimension, rating]) => {
      const value = ratingToNumber(rating);
      if (value !== null) (classDims[dimension] ||= []).push(value);
    });
  });

  const topicStats = topics.map(topic => {
    const dimensionValues = {};
    let uncertain = 0;
    inCourse.filter(response => response.topic_id === topic.id).forEach(response => {
      const scores = normalizeScores(response.teacher_dimension_scores || response.ai_dimension_scores);
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
    const quick = { good: 0, guide: 0, echo: 0 };
    inCourse.filter(r => r.student_id === st.id).forEach(r => {
      if (r.teacher_rating in quick) quick[r.teacher_rating] += 1;
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
    const avg = vals.length ? Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 100) / 100 : 0;
    const passLine = passLineForGrade(st.grade);
    return {
      student_id: st.id, name: st.name, grade: st.grade,
      cognitive_tier: st.grade <= 2 ? 'basic' : st.grade <= 5 ? 'developing' : 'advancing',
      avg_score: avg,
      pass_line: passLine,
      passing: avg > 0 && avg >= passLine,
      uncertain,
      bonus_flags: collectBonusFlags(inCourse.filter(r => r.student_id === st.id)),
      quick_ratings: quick,
    };
  });

  const avgs = studentStats.map(s => s.avg_score).filter(a => a > 0);
  const assessed = studentStats.filter(s => s.avg_score > 0);
  const passCount = assessed.filter(s => s.passing).length;
  const quickRatingCounts = { good: 0, guide: 0, echo: 0 };
  studentStats.forEach(s => {
    Object.entries(s.quick_ratings || {}).forEach(([k, v]) => { quickRatingCounts[k] += v; });
  });
  return {
    class_avg: avgs.length ? Math.round((avgs.reduce((a, b) => a + b, 0) / avgs.length) * 100) / 100 : 0,
    student_count: students.length,
    pass_count: passCount,
    pass_rate: assessed.length ? Math.round((passCount / assessed.length) * 100) / 100 : 0,
    class_dim_avg: Object.fromEntries(
      Object.entries(classDims).map(([dimension, values]) => [
        dimension,
        Math.round((values.reduce((sum, value) => sum + value, 0) / values.length) * 100) / 100,
      ]),
    ),
    topic_stats: topicStats,
    student_stats: studentStats,
    quick_rating_counts: quickRatingCounts,
    top_tags: (tags || [])
      .filter(tag => tag.course_id === courseId && tag.use_count > 0)
      .sort((a, b) => b.use_count - a.use_count)
      .slice(0, 10)
      .map(tag => ({ name: tag.name, count: tag.use_count, source: tag.source })),
  };
}
