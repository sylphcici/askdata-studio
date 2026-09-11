from __future__ import annotations

import unittest

from app.querying.summary_fidelity import SummaryFidelityChecker


class SummaryFidelityCheckerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = SummaryFidelityChecker()
        self.rows = [
            {"下单日期": "2026-07-08", "实付销售额": 12980.12},
            {"下单日期": "2026-07-18", "实付销售额": 103735.07},
            {"下单日期": "2026-07-19", "实付销售额": 20357.36},
        ]

    def test_correct_extrema_are_faithful(self) -> None:
        result = self.checker.check(
            "实付销售额最高的是7月18日，最低的是7月8日。",
            self.rows,
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.issues, [])

    def test_wrong_minimum_dimension_is_rejected(self) -> None:
        result = self.checker.check(
            "实付销售额最高的是7月18日，最低的是7月19日。",
            self.rows,
        )
        self.assertFalse(result.valid)
        self.assertIn("最低/最少", result.issues[0])

    def test_fallback_summary_uses_computed_facts(self) -> None:
        facts = self.checker.build_facts(self.rows)
        summary = self.checker.fallback_summary(facts)
        self.assertIn("2026-07-18", summary)
        self.assertIn("2026-07-08", summary)
        self.assertNotIn("2026-07-19）", summary.split("最低", 1)[-1])

    def test_wrong_reported_row_count_is_rejected(self) -> None:
        result = self.checker.check("所有50家返回结果中，A店最高。", self.rows)
        self.assertFalse(result.valid)
        self.assertIn("实际返回3行", result.issues[0])


if __name__ == "__main__":
    unittest.main()
