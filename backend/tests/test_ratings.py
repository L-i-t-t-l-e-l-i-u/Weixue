import unittest

from grading.ratings import (
    RATING_OPTIONS,
    RATING_VALUES,
    rating_to_value,
    pass_line_for_grade,
    is_passing,
)


class RatingScaleTests(unittest.TestCase):
    def test_six_level_order_and_values(self):
        self.assertEqual(RATING_OPTIONS, ("A+", "A", "A-", "B+", "B", "B-"))
        self.assertEqual(
            RATING_VALUES,
            {"A+": 4.0, "A": 3.5, "A-": 3.0, "B+": 2.5, "B": 2.0, "B-": 1.0},
        )

    def test_legacy_or_unknown_rating_is_not_silently_coerced(self):
        self.assertIsNone(rating_to_value("C"))
        self.assertIsNone(rating_to_value(""))


class PassLineTests(unittest.TestCase):
    def test_grade_bands_map_to_lines(self):
        # 1-3 年级 ≥ 2.5（B+）；4-6 年级及以上 ≥ 3.0（A-）
        for grade in (1, 2, 3):
            self.assertEqual(pass_line_for_grade(grade), 2.5)
        for grade in (4, 5, 6, 7):
            self.assertEqual(pass_line_for_grade(grade), 3.0)

    def test_is_passing_uses_own_grade_band(self):
        self.assertTrue(is_passing(2, 2.5))     # 低年级 B+ 达标
        self.assertFalse(is_passing(5, 2.5))    # 高年级 B+ 未达标
        self.assertTrue(is_passing(5, 3.0))     # 高年级 A- 达标
        self.assertFalse(is_passing(2, 2.4))
        self.assertFalse(is_passing(3, None))


if __name__ == "__main__":
    unittest.main()
