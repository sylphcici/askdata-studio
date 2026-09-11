import unittest

from app.preprocessing import RequestPreprocessor


class CountingModel:
    def __init__(self, action: str) -> None:
        self.action = action
        self.calls = 0

    def chat_json(self, system: str, user: str) -> dict:
        self.calls += 1
        if self.action == "data_qa":
            return {
                "action": "data_qa", "confidence": 0.9, "reason": "分析已有结果",
                # 验证问答路由会清空 Schema 检索参数。
                "standalone_query": "不应保留",
                "retrieval": {"retrieval_terms": ["销售额"]},
            }
        if self.action == "direct_response":
            return {
                "action": "direct_response",
                "confidence": 0.72,
                "reason": "无法确定用户希望查新数据还是分析已有结果",
                "response": "你希望查询新的销售数据，还是分析已有的销售结果？",
                "response_type": "clarification",
                "standalone_query": "不应保留",
                "retrieval": {"retrieval_terms": ["销售额"]},
            }
        return {
            "action": "database_query", "confidence": 0.9, "reason": "需要新数据",
            "standalone_query": "查询本月各地区销售额", "rewritten": True,
            "retrieval": {
                "retrieval_terms": ["地区", "销售额", "本月"],
                "metrics": ["销售额"], "dimensions": ["地区"],
                "filters": [], "time_expressions": ["本月"], "operations": ["汇总"],
            },
        }


class FailingModel:
    def chat_json(self, system: str, user: str) -> dict:
        raise RuntimeError("测试模型不可用")


class RequestPreprocessorTest(unittest.TestCase):
    def test_ambiguous_regional_average_price_uses_deterministic_business_options(self) -> None:
        model = CountingModel("database_query")
        result = RequestPreprocessor(model).prepare("按地区看平均单价", "")

        self.assertEqual(model.calls, 0)
        self.assertEqual(result.action, "database_query")
        self.assertEqual(result.source, "deterministic_business_guard")
        self.assertEqual(result.clarification["parameter"], "average_price_definition")
        self.assertEqual(
            [item["id"] for item in result.clarification["options"]],
            [
                "order_region_actual_unit_price",
                "store_region_list_price",
                "user_region_cart_unit_price",
            ],
        )

    def test_average_price_guard_supports_synonyms_and_recent_region_context(self) -> None:
        model = CountingModel("database_query")
        result = RequestPreprocessor(model).prepare(
            "改看单价均值", "上一轮：查看各大区销售表现"
        )

        self.assertEqual(model.calls, 0)
        self.assertIsNotNone(result.clarification)

    def test_explicit_average_price_source_keeps_existing_model_flow(self) -> None:
        model = CountingModel("database_query")
        result = RequestPreprocessor(model).prepare(
            "按订单地区统计平均成交单价", ""
        )

        self.assertEqual(model.calls, 1)
        self.assertIsNone(result.clarification)

    def test_sku_master_price_enriches_schema_retrieval_path(self) -> None:
        class SkuPriceModel:
            def chat_json(self, system: str, user: str) -> dict:
                return {
                    "action": "database_query",
                    "confidence": 0.95,
                    "reason": "查询SKU主数据定价",
                    "standalone_query": "按店铺所属大区统计SKU销售价的平均值",
                    "retrieval": {
                        "retrieval_terms": ["SKU销售价", "店铺大区"],
                        "metrics": ["平均销售价"],
                        "dimensions": ["店铺大区"],
                        "filters": [],
                        "time_expressions": [],
                        "operations": ["平均", "分组"],
                    },
                }

        result = RequestPreprocessor(SkuPriceModel()).prepare(
            "按店铺所属大区统计SKU销售价的平均值", ""
        )

        self.assertIn("商品主表", result.retrieval.retrieval_terms)
        self.assertIn("店铺所属大区", result.retrieval.retrieval_terms)

    def test_missing_metric_returns_structured_clarification(self) -> None:
        class MissingMetricModel:
            def chat_json(self, system: str, user: str) -> dict:
                return {
                    "action": "database_query",
                    "confidence": 0.93,
                    "reason": "用户要查新数据，但没有明确指标",
                    "standalone_query": "查看各地区的销售情况",
                    "clarification": {
                        "parameter": "metric",
                        "question": "你希望用哪个指标查看各地区的销售情况？",
                        "reason": "不同指标会产生不同结果",
                    },
                    "retrieval": {
                        "retrieval_terms": ["地区"],
                        "metrics": [],
                        "dimensions": ["地区"],
                        "filters": [],
                        "time_expressions": [],
                        "operations": ["group_by"],
                    },
                }

        result = RequestPreprocessor(MissingMetricModel()).prepare(
            "查看各地区的销售情况", ""
        )

        self.assertEqual(result.action, "database_query")
        self.assertEqual(result.clarification["parameter"], "metric")
        self.assertEqual(
            [item["label"] for item in result.clarification["options"]],
            ["实付销售额", "订单量", "客单价"],
        )
        self.assertEqual(result.retrieval.metrics, [])

    def test_database_request_finishes_three_tasks_in_one_model_call(self) -> None:
        model = CountingModel("database_query")
        result = RequestPreprocessor(model).prepare("各地区呢", "上一轮查询本月销售额")
        self.assertEqual(model.calls, 1)
        self.assertEqual(result.action, "database_query")
        self.assertEqual(result.standalone_query, "查询本月各地区销售额")
        self.assertEqual(result.retrieval.retrieval_terms, ["地区", "销售额", "本月"])

    def test_actual_rewrite_overrides_incorrect_model_flag(self) -> None:
        class IncorrectFlagModel(CountingModel):
            def chat_json(self, system: str, user: str) -> dict:
                payload = super().chat_json(system, user)
                payload["rewritten"] = False
                return payload

        result = RequestPreprocessor(IncorrectFlagModel("database_query")).prepare(
            "换成6月", "上一轮统计2026年7月华东和华南销售额"
        )
        self.assertTrue(result.rewritten)

    def test_qa_clears_query_and_retrieval_output(self) -> None:
        model = CountingModel("data_qa")
        result = RequestPreprocessor(model).prepare("解释刚才的结果", "有上一轮结果")
        self.assertEqual(model.calls, 1)
        self.assertEqual(result.action, "data_qa")
        self.assertEqual(result.standalone_query, "")
        self.assertEqual(result.retrieval.retrieval_terms, [])

    def test_model_failure_uses_explicit_conservative_fallback(self) -> None:
        result = RequestPreprocessor(FailingModel()).prepare("查询本月销售额", "")

        self.assertEqual(result.action, "direct_response")
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.source, "model_unavailable_fallback")
        self.assertIn("暂时不可用", result.response)
        self.assertIn("测试模型不可用", result.reason)

    def test_gray_zone_is_clarified_by_preprocessor_without_retrieval(self) -> None:
        model = CountingModel("direct_response")

        result = RequestPreprocessor(model).prepare("看看销售情况", "有一张销售结果表")

        self.assertEqual(model.calls, 1)
        self.assertEqual(result.action, "direct_response")
        self.assertEqual(result.response_type, "clarification")
        self.assertIn("查询新的销售数据", result.response)
        self.assertEqual(result.standalone_query, "")
        self.assertEqual(result.retrieval.retrieval_terms, [])


if __name__ == "__main__":
    unittest.main()
