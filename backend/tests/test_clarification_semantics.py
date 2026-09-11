from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.workflows.query_graph import QueryWorkflow


class ClarificationSemanticsTest(unittest.TestCase):
    def test_join_authorization_clarification_becomes_failure(self) -> None:
        technical = {
            "parameter": "join_definition",
            "question": "如何关联订单明细与订单地区？",
            "reason": "Schema允许的JOIN列表中不包含所需关联关系",
            "options": [
                {"id": "allow_join", "label": "允许通过技术字段关联", "description": ""},
                {"id": "stop", "label": "终止查询", "description": ""},
            ],
        }
        workflow = object.__new__(QueryWorkflow)
        workflow.single_database_agent = SimpleNamespace(
            prepare=lambda *args, **kwargs: {
                "action": "clarify",
                "clarification": technical,
                "tool_trace": [],
            }
        )
        state = {
            "standalone_query": "按订单地区统计平均单价",
            "query": "平均单价",
            "database_names": ["askdata_mock"],
            "schema_graph": {},
            "schema_context": "",
            "retrieval": {},
            "workspace": {},
            "access_scope": {},
        }

        update = workflow._prepare_single_database(state)

        self.assertIsNone(update["clarification"])
        self.assertFalse(update["mcp_execution"]["success"])
        self.assertIn("缺少可靠的关联关系", update["mcp_execution"]["error"])

    def test_business_clarification_still_waits_for_user(self) -> None:
        business = {
            "parameter": "region_definition",
            "question": "这里的地区按什么归属统计？",
            "reason": "不同地区口径会改变结果",
            "options": [
                {"id": "order_region", "label": "订单地区", "description": "按订单归属地区"},
                {"id": "store_region", "label": "店铺地区", "description": "按店铺所属地区"},
            ],
        }
        workflow = object.__new__(QueryWorkflow)
        workflow.single_database_agent = SimpleNamespace(
            prepare=lambda *args, **kwargs: {
                "action": "clarify",
                "clarification": business,
                "tool_trace": [],
            }
        )
        state = {
            "standalone_query": "按地区统计平均单价",
            "query": "平均单价",
            "database_names": ["askdata_mock"],
            "schema_graph": {},
            "schema_context": "",
            "retrieval": {},
            "workspace": {},
            "access_scope": {},
        }

        update = workflow._prepare_single_database(state)

        self.assertEqual(update["clarification"], business)
        self.assertNotIn("mcp_execution", update)

    def test_non_table_clarification_keeps_full_selected_semantics(self) -> None:
        state = {
            "query": "平均单价",
            "standalone_query": "按地区查看平均单价",
            "workspace": {},
            "extraction": {"retrieval_terms": ["平均单价", "地区"]},
            "clarification": {
                "parameter": "average_price_definition",
                "question": "请选择平均单价口径",
                "options": [
                    {
                        "id": "order_region_actual_unit_price",
                        "label": "按订单大区统计实际成交平均单价",
                        "description": "地区使用订单大区，单价使用订单明细成交单价",
                    },
                    {
                        "id": "store_region_list_price",
                        "label": "按店铺大区统计商品标价",
                        "description": "地区使用店铺大区",
                    },
                ],
            },
        }

        with patch(
            "app.workflows.query_graph.interrupt",
            return_value={"option_id": "order_region_actual_unit_price"},
        ):
            update = QueryWorkflow._human_clarification(object(), state)

        self.assertIn("按订单大区统计实际成交平均单价", update["standalone_query"])
        self.assertIn("地区使用订单大区", update["standalone_query"])
        self.assertEqual(
            update["extraction"]["retrieval_terms"],
            ["平均单价", "地区", "按订单大区统计实际成交平均单价"],
        )
        self.assertTrue(update["rewritten"])
        self.assertEqual(
            update["workspace"]["confirmed_parameters"]["average_price_definition"],
            "order_region_actual_unit_price",
        )

    def test_existing_metric_clarification_behavior_is_preserved(self) -> None:
        state = {
            "query": "看各地区销售情况",
            "standalone_query": "看各地区销售情况",
            "workspace": {},
            "extraction": {"retrieval_terms": ["地区"], "metrics": []},
            "clarification": {
                "parameter": "metric",
                "question": "请选择指标",
                "options": [
                    {
                        "id": "order_count",
                        "label": "订单量",
                        "description": "按订单数量统计",
                    },
                    {
                        "id": "paid_amount",
                        "label": "实付销售额",
                        "description": "按实付金额汇总",
                    },
                ],
            },
        }

        with patch(
            "app.workflows.query_graph.interrupt",
            return_value={"option_id": "order_count"},
        ):
            update = QueryWorkflow._human_clarification(object(), state)

        self.assertEqual(update["standalone_query"], "看各地区销售情况，指标使用订单量")
        self.assertEqual(update["extraction"]["metrics"], ["订单量"])
        self.assertEqual(update["extraction"]["retrieval_terms"], ["地区", "订单量"])


if __name__ == "__main__":
    unittest.main()
