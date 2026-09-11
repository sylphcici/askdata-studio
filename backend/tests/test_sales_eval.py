from __future__ import annotations

import json
import unittest

from app.querying.duckdb_engine import DuckDbEngine
from scripts.evaluate_sales import (
    DEFAULT_DATASET,
    classify_failure,
    compare_results,
    parse_sql_objects,
    summarize,
    validate_dataset,
)


class SalesEvaluationTest(unittest.TestCase):
    def test_shipping_package_case_uses_package_quantity_not_shipment_rows(self) -> None:
        dataset = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
        case = next(item for item in dataset["cases"] if item["id"] == "sales_018")
        self.assertIn("package_count", case["expected_fields"])
        self.assertNotIn("shipment_id", case["expected_fields"])
        self.assertIn("SUM(package_count)", case["gold_sql"])

    def test_all_golden_queries_are_valid(self) -> None:
        dataset = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
        with DuckDbEngine().connect(dataset["database"]) as connection:
            cases = validate_dataset(dataset, connection)

        self.assertEqual(len(cases), 20)
        self.assertTrue(all(case["expected_rows"] for case in cases))

    def test_sql_object_parser_excludes_cte_aliases(self) -> None:
        tables, fields = parse_sql_objects(
            "WITH totals AS (SELECT store_id, SUM(gmv) AS value FROM daily_store_metrics "
            "GROUP BY store_id) SELECT store_id, value FROM totals"
        )
        self.assertEqual(tables, {"daily_store_metrics"})
        self.assertIn("store_id", fields)
        self.assertIn("gmv", fields)

    def test_result_comparison_ignores_aliases_and_column_order(self) -> None:
        expected = [{"地区": "华东", "销售额": 100.1256}]
        actual = [{"实付金额": 100.1256, "销售地区": "华东"}]
        matched, _ = compare_results(actual, expected)
        self.assertTrue(matched)

    def test_result_comparison_accepts_equivalent_month_pivot(self) -> None:
        expected = [
            {"月份": "2026-06", "实付销售额": 2028492.68},
            {"月份": "2026-07", "实付销售额": 1849806.19},
        ]
        actual = [{
            "2026年6月实付销售额": 2028492.68,
            "2026年7月实付销售额": 1849806.19,
        }]
        matched, detail = compare_results(actual, expected)
        self.assertTrue(matched)
        self.assertIn("布局等价", detail)

    def test_result_comparison_allows_display_rounding(self) -> None:
        expected = [{"地区": "华东", "平均实付金额": 2496.46}]
        actual = [{"平均金额": 2496.45678, "销售地区": "华东"}]
        matched, _ = compare_results(actual, expected)
        self.assertTrue(matched)

    def test_result_comparison_allows_extra_derived_column(self) -> None:
        expected = [{"店铺": "A店", "净收入": 80, "目标": 100}]
        actual = [{"店铺名称": "A店", "累计净收入": 80, "净收入目标": 100, "偏差率": -0.2}]
        matched, _ = compare_results(actual, expected)
        self.assertTrue(matched)

    def test_result_comparison_normalizes_equivalent_month_labels(self) -> None:
        expected = [{"月份": "2026-06", "销售额": 100}]
        for month_value in ("2026年6月", "2026-06-01", "2026-06-01 00:00:00"):
            matched, _ = compare_results(
                [{"month": month_value, "amount": 100}], expected
            )
            self.assertTrue(matched)

    def test_result_comparison_normalizes_midnight_as_same_day(self) -> None:
        matched, _ = compare_results(
            [{"日期": "2026-07-18 00:00:00", "金额": 100}],
            [{"日期": "2026-07-18", "金额": 100}],
        )
        self.assertTrue(matched)

    def test_summary_reports_stable_accuracy_across_repeats(self) -> None:
        base = {
            "table_recall": 1.0,
            "field_recall": 1.0,
            "latency_seconds": 10.0,
            "summary_faithful": True,
            "summary_guard_used": False,
            "displayed_summary_faithful": True,
        }
        results = [
            {**base, "id": "case-a", "execution_success": True, "result_match": True, "failure_reason": ""},
            {**base, "id": "case-a", "execution_success": False, "result_match": False, "failure_reason": "模型超时"},
            {**base, "id": "case-b", "execution_success": True, "result_match": True, "failure_reason": ""},
            {**base, "id": "case-b", "execution_success": True, "result_match": True, "failure_reason": ""},
        ]
        summary = summarize("test", results)
        self.assertEqual(summary["p95_latency_seconds"], 10.0)
        self.assertEqual(summary["case_count"], 2)
        self.assertEqual(summary["run_count"], 4)
        self.assertEqual(summary["case_pass_rate"], 1.0)
        self.assertEqual(summary["stable_case_accuracy"], 0.5)

    def test_p95_uses_nearest_rank(self) -> None:
        base = {
            "id": "case-a",
            "table_recall": 1.0,
            "field_recall": 1.0,
            "execution_success": True,
            "result_match": True,
            "summary_faithful": True,
            "summary_guard_used": False,
            "displayed_summary_faithful": True,
            "failure_reason": "",
        }
        results = [
            {**base, "latency_seconds": 21.989},
            {**base, "latency_seconds": 22.486},
            {**base, "latency_seconds": 24.332},
        ]
        self.assertEqual(summarize("test", results)["p95_latency_seconds"], 24.332)

    def test_completed_wrong_result_is_not_mislabeled_as_sql_error(self) -> None:
        reason = classify_failure(
            "completed",
            "SQL已成功执行，但result_analysis失败",
            False,
        )
        self.assertEqual(reason, "结果不一致")


if __name__ == "__main__":
    unittest.main()
