from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.querying.duckdb_engine import DuckDbEngine
from scripts.evaluate_sales import evaluate_case, parse_sql_objects, summarize


DATASET = Path(__file__).resolve().parents[1] / "evals" / "core_capabilities_golden.json"


class CoreCapabilitiesDatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = json.loads(DATASET.read_text(encoding="utf-8"))

    def test_ids_are_unique_and_required_capabilities_are_present(self) -> None:
        cases = self.dataset["cases"]
        ids = [case["id"] for case in cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            {case["kind"] for case in cases},
            {"query", "clarification", "safety", "permission"},
        )
        categories = {case["category"] for case in cases}
        self.assertTrue(
            {
                "缺少指标",
                "地区与单价口径",
                "真实业务Demo",
                "业务语义区分",
                "多表合法关联",
                "只读安全",
                "权限隔离",
            }.issubset(categories)
        )

    def test_every_gold_sql_is_executable_and_matches_declared_schema(self) -> None:
        engine = DuckDbEngine()
        with engine.connect(self.dataset["database"]) as connection:
            for case in self.dataset["cases"]:
                sql = case.get("gold_sql")
                if not sql:
                    continue
                with self.subTest(case=case["id"]):
                    tables, fields = parse_sql_objects(sql)
                    self.assertTrue(set(case["expected_tables"]).issubset(tables))
                    self.assertTrue(set(case["expected_fields"]).issubset(fields))
                    connection.execute(sql).fetchall()

    def test_clarification_cases_define_auditable_follow_up(self) -> None:
        cases = [case for case in self.dataset["cases"] if case["kind"] == "clarification"]
        self.assertGreaterEqual(len(cases), 2)
        for case in cases:
            with self.subTest(case=case["id"]):
                expected = case["expected_clarification"]
                self.assertTrue(
                    expected.get("parameter")
                    or expected.get("required_option_term_groups")
                    or expected.get("required_option_patterns")
                )
                if expected.get("required_option_ids"):
                    self.assertGreaterEqual(len(expected["required_option_ids"]), 2)
                    self.assertIn(case["response"]["option_id"], expected["required_option_ids"])
                else:
                    patterns = expected.get("required_option_patterns", [])
                    term_groups = expected.get("required_option_term_groups", [])
                    self.assertGreaterEqual(len(patterns or term_groups), 2)
                    self.assertTrue(
                        case["response"].get("match_pattern")
                        or case["response"].get("match_terms")
                    )
                self.assertEqual(case["expected_final_status"], "completed")

    def test_safety_cases_do_not_contain_executable_gold_sql(self) -> None:
        safety = next(case for case in self.dataset["cases"] if case["kind"] == "safety")
        self.assertNotIn("gold_sql", safety)
        self.assertTrue(safety["must_not_execute_sql"])
        self.assertIn("DELETE", safety["forbidden_sql_patterns"])

    @staticmethod
    def result(**overrides):
        values = {
            "task_id": "task-1",
            "status": "completed",
            "sql": "SELECT region, COUNT(order_id) FROM orders GROUP BY region",
            "rows": [{"地区": "华东", "订单量": 2}],
            "analysis": "华东订单量为2。",
            "summary_faithful": True,
            "summary_guard_used": False,
            "summary_fidelity_issues": [],
            "clarification": None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_clarification_case_evaluates_both_turns(self) -> None:
        initial = self.result(
            status="waiting_clarification",
            sql=None,
            rows=[],
            analysis="请选择指标。",
            clarification=SimpleNamespace(
                parameter="metric",
                options=[
                    SimpleNamespace(id="paid_amount"),
                    SimpleNamespace(id="order_count"),
                    SimpleNamespace(id="average_order_value"),
                ],
            ),
        )
        final = self.result()

        class Service:
            def submit(self, *args, **kwargs):
                return initial

            def clarify(self, *args, **kwargs):
                return final

        case = next(item for item in self.dataset["cases"] if item["id"] == "core_003")
        outcome = evaluate_case(Service(), case, final.rows, self.dataset["user_id"])
        self.assertTrue(outcome["clarification_match"])
        self.assertTrue(outcome["multiturn_completed"])
        self.assertTrue(outcome["capability_pass"])

    def test_safety_and_permission_have_separate_metrics(self) -> None:
        class SafetyService:
            def submit(self, *args, **kwargs):
                return CoreCapabilitiesDatasetTest.result(
                    sql=None, rows=[], analysis="仅支持只读查询。"
                )

        safety_case = next(
            item for item in self.dataset["cases"] if item["id"] == "core_008"
        )
        outcome = evaluate_case(
            SafetyService(), safety_case, [], self.dataset["user_id"]
        )
        self.assertTrue(outcome["safety_pass"])
        summary = summarize("test", [outcome])
        self.assertEqual(summary["safety_pass_rate"], 1.0)
        self.assertIsNone(summary["query_accuracy"])
        self.assertIsNone(summary["sql_execution_success_rate"])

    def test_sql_success_rate_excludes_non_sql_safety_cases(self) -> None:
        query_result = {
            "id": "query",
            "kind": "query",
            "sql_expected": True,
            "execution_success": True,
            "result_match": True,
            "capability_pass": True,
            "summary_faithful": True,
            "displayed_summary_faithful": True,
            "summary_guard_used": False,
            "table_recall": 1.0,
            "field_recall": 1.0,
            "latency_seconds": 1.0,
            "failure_reason": "",
        }
        safety_result = {
            **query_result,
            "id": "safety",
            "kind": "safety",
            "sql_expected": False,
            "execution_success": False,
            "safety_pass": True,
        }
        # 兼容修复前已经持久化、尚未写入sql_expected字段的报告。
        safety_result.pop("sql_expected")

        summary = summarize("test", [query_result, safety_result])

        self.assertEqual(summary["sql_execution_success_rate"], 1.0)
        self.assertEqual(summary["sql_execution_success_count"], 1)
        self.assertEqual(summary["sql_expected_run_count"], 1)

    def test_business_clarification_accepts_dynamic_ids_by_visible_semantics(self) -> None:
        initial = self.result(
            status="waiting_clarification",
            sql=None,
            rows=[],
            analysis="请选择平均单价口径。",
            clarification=SimpleNamespace(
                parameter="price_scope_generated_by_model",
                question="请选择平均单价和地区口径",
                reason="不同业务口径会改变结果",
                options=[
                    SimpleNamespace(
                        id="dynamic-a",
                        label="已成交订单的实际平均单价",
                        description="按订单所属大区统计",
                    ),
                    SimpleNamespace(
                        id="dynamic-b",
                        label="商品SKU销售标价的平均值",
                        description="按店铺所属大区统计",
                    ),
                ],
            ),
        )
        final = self.result()
        selected = []

        class Service:
            def submit(self, *args, **kwargs):
                return initial

            def clarify(self, task_id, option_id, **kwargs):
                selected.append(option_id)
                return final

        case = next(item for item in self.dataset["cases"] if item["id"] == "core_004")
        outcome = evaluate_case(Service(), case, final.rows, self.dataset["user_id"])
        self.assertEqual(selected, ["dynamic-a"])
        self.assertTrue(outcome["clarification_match"])
        self.assertTrue(outcome["capability_pass"])
        self.assertEqual(outcome["clarification"]["parameter"], "price_scope_generated_by_model")


if __name__ == "__main__":
    unittest.main()
