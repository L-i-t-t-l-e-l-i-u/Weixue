export const RATING_VALUES = Object.freeze({
  'A+': 4,
  'A': 3.5,
  'A-': 3,
  'B+': 2.5,
  'B': 2,
  'B-': 1,
});

export const RATING_OPTIONS = Object.freeze(Object.keys(RATING_VALUES));

export const ratingToNumber = (rating) => RATING_VALUES[rating] ?? null;

// ── 合格线（教师口径，2026-08 确认）────────────────────────
// 1-3 年级 ≥ 2.5（B+）；4-6 年级及以上 ≥ 3.0（A-）。按学生自己的年级判断。
export const PASS_LINES = Object.freeze({
  lower: 2.5,
  upper: 3.0,
});

export const passLineForGrade = (grade) =>
  grade >= 1 && grade <= 3 ? PASS_LINES.lower : PASS_LINES.upper;

export const isPassing = (grade, value) =>
  value !== null && value !== undefined && value >= passLineForGrade(grade);

// 企业加分项：命中“有自己 / 有新意”可提升一级评级（A → A+）
export const BONUS_FLAGS = Object.freeze(['有自己', '有新意']);

export const applyBonusUpgrade = (rating, bonusFlags) => {
  if (!rating || !Array.isArray(bonusFlags) || bonusFlags.length === 0) return rating;
  if (!RATING_OPTIONS.includes(rating) || rating === 'A+') return rating;
  const idx = RATING_OPTIONS.indexOf(rating);
  return RATING_OPTIONS[Math.max(idx - 1, 0)];
};

// 综合评级档位（与全站展示口径一致：优秀/良好/待提升/薄弱）
export const BAND_ORDER = Object.freeze(['优秀', '良好', '待提升', '薄弱']);

export const bandFromAverage = (avg, passLine = PASS_LINES.lower) => {
  if (avg >= 3.5) return '优秀';
  if (avg >= passLine) return '良好';
  if (avg >= 1.5) return '待提升';
  if (avg > 0) return '薄弱';
  return '未评';
};

/** 按学生年级合格线取综合评级档位。 */
export const bandForGrade = (avg, grade) =>
  bandFromAverage(avg, passLineForGrade(grade));

// 企业加分项：命中可让综合评级提升一档（良好→优秀 / 待提升→良好 / 薄弱→待提升）
export const upgradeBand = (band, bonusFlags) => {
  if (!band || !Array.isArray(bonusFlags) || bonusFlags.length === 0) return band;
  const idx = BAND_ORDER.indexOf(band);
  if (idx <= 0) return band;
  return BAND_ORDER[idx - 1];
};

// 汇总多个作答的加分项（去重），用于学生级综合评级
export const collectBonusFlags = (responses) => {
  const set = new Set();
  (responses || []).forEach(r => (r.ai_bonus_flags || []).forEach(f => set.add(f)));
  return Array.from(set);
};

// 维度 key 归一化：中文维度名 / 旧版 key 统一映射到五维度标准 key
export const DIMENSION_KEY_ALIASES = {
  立意: 'position', '立意（观点鲜明）': 'position',
  选材: 'material', '选材（言之有物）': 'material',
  结构: 'structure', '结构（条理清晰）': 'structure',
  语言: 'language', '语言（用词准确）': 'language',
  视角: 'perspective', '视角（换位思考）': 'perspective',
  clarity: 'position', interpretation: 'position',
  evidence_awareness: 'material', evidence_use: 'material',
  relevance: 'structure', inference: 'structure', argument_evaluation: 'structure',
  depth_breadth: 'perspective', self_regulation: 'perspective',
};

export const normalizeScores = (scores) => {
  if (!scores || typeof scores !== 'object') return scores;
  const out = {};
  Object.entries(scores).forEach(([k, v]) => { out[DIMENSION_KEY_ALIASES[k] || k] = v; });
  return out;
};

export const averageRating = (scores) => {
  if (!scores || typeof scores !== 'object') return 0;
  const values = Object.values(scores)
    .map(ratingToNumber)
    .filter(value => value !== null);
  return values.length > 0
    ? values.reduce((sum, value) => sum + value, 0) / values.length
    : 0;
};

// Compatibility aliases for components introduced in the collaborator branch.
export const RATING_TO_NUM = RATING_VALUES;
export const avgRating = averageRating;
