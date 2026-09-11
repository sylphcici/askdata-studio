from __future__ import annotations

import unittest

from app.querying.single_database_agent import SingleDatabaseAgent


class SqlProductContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = {
            "fields": [
                {"name": "store_id"},
                {"name": "store_name"},
                {"name": "stat_date"},
                {"name": "gmv"},
                {"name": "gmv_target"},
            ],
            "joins": [
                {
                    "left_table_name": "products",
                    "left_field": "product_id",
                    "right_table_name": "daily_product_metrics",
                    "right_field": "product_id",
                }
            ],
            "tables": [
                {"id": "products", "name": "products"},
                {"id": "daily_product_metrics", "name": "daily_product_metrics"},
            ],
        }

    def test_explicit_month_does_not_need_time_tools(self) -> None:
        self.assertFalse(
            SingleDatabaseAgent._requires_time_resolution("统计2026年7月各地区销售额")
        )
        self.assertFalse(
            SingleDatabaseAgent._requires_time_resolution("换成2026-06")
        )

    def test_relative_month_still_uses_time_tools(self) -> None:
        self.assertTrue(
            SingleDatabaseAgent._requires_time_resolution("统计本月各地区销售额")
        )

    def test_monthly_store_summary_rejects_unrequested_daily_grain(self) -> None:
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT stat_date, store_id, SUM(gmv) FROM daily_store_metrics "
            "GROUP BY stat_date, store_id",
            "按统计日期汇总2026年7月各店铺的GMV",
            self.graph,
        )
        self.assertIn("结果粒度错误", error or "")

    def test_rate_must_not_be_multiplied_by_one_hundred(self) -> None:
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT store_name, SUM(gmv) / MAX(gmv_target) * 100 AS 完成率 "
            "FROM stores GROUP BY store_name",
            "计算各店铺完成率",
            self.graph,
        )
        self.assertIn("比例单位错误", error or "")

    def test_business_dimension_prefers_name_over_identifier(self) -> None:
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT store_id, SUM(gmv) FROM daily_store_metrics GROUP BY store_id",
            "统计各店铺GMV",
            self.graph,
        )
        self.assertIn("展示字段错误", error or "")

    def test_valid_store_summary_passes_contract(self) -> None:
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT store_name, SUM(gmv) FROM daily_store_metrics "
            "WHERE stat_date >= '2026-07-01' GROUP BY store_name",
            "汇总2026年7月各店铺GMV",
            self.graph,
        )
        self.assertIsNone(error)

    def test_single_table_detail_requires_record_identifier(self) -> None:
        graph = {
            "fields": [
                {"name": "resource_id", "role": "identifier"},
                {"name": "cn_file_name"},
                {"name": "image_path"},
            ],
            "tables": [
                {
                    "id": "ecommerce_ops.media_resources",
                    "name": "media_resources",
                    "primary_key": ["resource_id"],
                }
            ],
            "joins": [],
        }
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT cn_file_name FROM media_resources "
            "WHERE image_path = 'public_third_part.jpeg'",
            "帮我找出还没有配置专属封面的歌曲",
            graph,
        )
        self.assertIn("交付字段缺失", error or "")

    def test_single_table_detail_with_identifier_passes_contract(self) -> None:
        graph = {
            "fields": [
                {"name": "resource_id", "role": "identifier"},
                {"name": "cn_file_name"},
                {"name": "image_path"},
            ],
            "tables": [
                {
                    "id": "ecommerce_ops.media_resources",
                    "name": "media_resources",
                    "primary_key": ["resource_id"],
                }
            ],
            "joins": [],
        }
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT resource_id, cn_file_name FROM media_resources "
            "WHERE image_path = 'public_third_part.jpeg'",
            "帮我找出还没有配置专属封面的歌曲",
            graph,
        )
        self.assertIsNone(error)

    def test_missing_cover_address_rejects_default_cover_value(self) -> None:
        graph = {
            "fields": [{"name": "resource_id"}, {"name": "image_path"}],
            "tables": [{"id": "ecommerce_ops.media_resources", "name": "media_resources"}],
            "joins": [],
        }
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT resource_id, image_path FROM media_resources "
            "WHERE image_path IS NULL OR image_path = '' "
            "OR image_path = 'public_third_part.jpeg'",
            "找出没有封面地址的歌曲",
            graph,
        )
        self.assertIn("筛选语义错误", error or "")

    def test_missing_cover_address_requires_null_and_blank(self) -> None:
        graph = {
            "fields": [{"name": "resource_id"}, {"name": "image_path"}],
            "tables": [{"id": "ecommerce_ops.media_resources", "name": "media_resources"}],
            "joins": [],
        }
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT resource_id, image_path FROM media_resources WHERE image_path IS NULL",
            "找出没有封面地址的歌曲",
            graph,
        )
        self.assertIn("筛选条件缺失", error or "")

    def test_missing_cover_address_accepts_null_or_trimmed_blank(self) -> None:
        graph = {
            "fields": [{"name": "resource_id"}, {"name": "image_path"}],
            "tables": [{"id": "ecommerce_ops.media_resources", "name": "media_resources"}],
            "joins": [],
        }
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT resource_id, image_path FROM media_resources "
            "WHERE image_path IS NULL OR TRIM(image_path) = ''",
            "找出没有封面地址的歌曲",
            graph,
        )
        self.assertIsNone(error)

    def test_sku_master_price_rejects_transaction_fact_tables(self) -> None:
        graph = {
            "fields": [
                {"name": "store_id"}, {"name": "product_id"},
                {"name": "region"}, {"name": "sale_price"},
            ],
            "tables": [
                {"id": name, "name": name}
                for name in ("stores", "orders", "order_items", "product_skus", "products")
            ],
            "joins": [],
        }
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT s.region, AVG(ps.sale_price) FROM stores s "
            "JOIN orders o ON s.store_id = o.store_id "
            "JOIN order_items i ON o.order_id = i.order_id "
            "JOIN product_skus ps ON i.sku_id = ps.sku_id GROUP BY s.region",
            "按店铺所属大区统计SKU销售价的平均值",
            graph,
        )
        self.assertIn("统计总体错误", error or "")

    def test_sku_master_price_accepts_master_data_join_path(self) -> None:
        graph = {
            "fields": [
                {"name": "store_id"}, {"name": "product_id"},
                {"name": "region"}, {"name": "sale_price"},
            ],
            "tables": [
                {"id": name, "name": name}
                for name in ("stores", "product_skus", "products")
            ],
            "joins": [
                {"left_table_name": "product_skus", "left_field": "product_id", "right_table_name": "products", "right_field": "product_id"},
                {"left_table_name": "products", "left_field": "store_id", "right_table_name": "stores", "right_field": "store_id"},
            ],
        }
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT s.region, AVG(ps.sale_price) FROM product_skus ps "
            "JOIN products p ON ps.product_id = p.product_id "
            "JOIN stores s ON p.store_id = s.store_id GROUP BY s.region",
            "按店铺所属大区统计SKU销售价的平均值",
            graph,
        )
        self.assertIsNone(error)

    def test_summary_query_does_not_require_identifier(self) -> None:
        graph = {
            "fields": [{"name": "resource_id"}, {"name": "category"}],
            "tables": [
                {
                    "id": "ecommerce_ops.media_resources",
                    "name": "media_resources",
                    "primary_key": ["resource_id"],
                }
            ],
            "joins": [],
        }
        contract = SingleDatabaseAgent._result_contract(
            "统计各分类的歌曲数量", graph
        )
        self.assertEqual(contract["required_identifiers"], [])

    def test_detail_query_requires_configured_readable_fields(self) -> None:
        graph = {
            "fields": [
                {"name": "resource_id"},
                {"name": "cn_file_name"},
                {"name": "artist"},
                {"name": "image_path"},
            ],
            "tables": [
                {
                    "id": "ecommerce_ops.media_resources",
                    "name": "media_resources",
                    "primary_key": ["resource_id"],
                    "default_detail_fields": [
                        "resource_id", "cn_file_name", "artist", "image_path"
                    ],
                }
            ],
            "joins": [],
        }
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT resource_id, image_path FROM media_resources "
            "WHERE image_path = 'public_third_part.jpeg'",
            "帮我找出还没有配置专属封面的歌曲",
            graph,
        )
        self.assertIn("业务字段缺失", error or "")

    def test_join_rejects_same_named_but_undeclared_key(self) -> None:
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT p.product_name, SUM(d.gmv) FROM daily_product_metrics d "
            "JOIN products p ON d.store_id = p.store_id GROUP BY p.product_name",
            "\u7edf\u8ba1\u5404\u5546\u54c1GMV",
            self.graph,
        )
        self.assertIn("\u5173\u8054\u5173\u7cfb\u9519\u8bef", error or "")

    def test_join_accepts_declared_relationship(self) -> None:
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT p.product_name, SUM(d.gmv) FROM daily_product_metrics d "
            "JOIN products p ON d.product_id = p.product_id GROUP BY p.product_name",
            "\u7edf\u8ba1\u5404\u5546\u54c1GMV",
            self.graph,
        )
        self.assertIsNone(error)

    def test_join_rejects_membership_filter_that_does_not_link_tables(self) -> None:
        graph = {
            "fields": [
                {"name": "region"},
                {"name": "unit_price"},
                {"name": "sku_id"},
            ],
            "tables": [
                {"id": "orders", "name": "orders"},
                {"id": "users", "name": "users"},
                {"id": "order_items", "name": "order_items"},
                {"id": "product_skus", "name": "product_skus"},
            ],
            "joins": [
                {
                    "left_table_name": "orders",
                    "left_field": "user_id",
                    "right_table_name": "users",
                    "right_field": "user_id",
                }
            ],
        }
        error = SingleDatabaseAgent._sql_contract_error(
            'SELECT o.region, AVG(oi.unit_price) FROM orders o '
            'JOIN users u ON o.user_id = u.user_id '
            'JOIN order_items oi ON oi.sku_id IN '
            '(SELECT sku_id FROM product_skus) GROUP BY o.region',
            "按订单地区统计平均单价",
            graph,
        )
        self.assertIn("JOIN的ON条件必须使用Schema声明的字段等值关系", error or "")

    def test_join_rejects_constant_on_condition(self) -> None:
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT p.product_name, SUM(d.gmv) FROM daily_product_metrics d "
            "JOIN products p ON 1 = 1 GROUP BY p.product_name",
            "统计各商品GMV",
            self.graph,
        )
        self.assertIn("JOIN的ON条件必须使用Schema声明的字段等值关系", error or "")

    def test_join_accepts_database_qualified_schema_relationship(self) -> None:
        graph = {
            **self.graph,
            "tables": [
                {"id": "ecommerce_ops.products", "name": "products"},
                {
                    "id": "ecommerce_ops.daily_product_metrics",
                    "name": "daily_product_metrics",
                },
            ],
            "joins": [
                {
                    "left_table": "ecommerce_ops.products",
                    "left_field": "product_id",
                    "right_table": "ecommerce_ops.daily_product_metrics",
                    "right_field": "product_id",
                }
            ],
        }
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT p.product_name, SUM(d.gmv) FROM daily_product_metrics d "
            "JOIN products p ON d.product_id = p.product_id GROUP BY p.product_name",
            "\u7edf\u8ba1\u5404\u5546\u54c1GMV",
            graph,
        )
        self.assertIsNone(error)

    def test_join_validation_ignores_cte_to_physical_table_join(self) -> None:
        error = SingleDatabaseAgent._sql_contract_error(
            "WITH totals AS (SELECT product_id, SUM(gmv) AS total_gmv "
            "FROM daily_product_metrics GROUP BY product_id) "
            "SELECT p.product_name, t.total_gmv FROM totals t "
            "JOIN products p ON t.product_id = p.product_id",
            "\u7edf\u8ba1\u5404\u5546\u54c1GMV",
            self.graph,
        )
        self.assertIsNone(error)

    def test_result_contract_requires_store_grain_without_time_grouping(self) -> None:
        contract = SingleDatabaseAgent._result_contract(
            "\u7edf\u8ba12026\u5e747\u6708\u5404\u5e97\u94fagmv\u548c\u76ee\u6807",
            self.graph,
        )
        self.assertEqual(contract["required_group_dimensions"], ["store_name"])
        self.assertEqual(contract["time_grain"], "filter_only")
        self.assertEqual(contract["rate_representation"], "0_to_1_decimal")

    def test_find_below_target_rejects_case_only_without_filter(self) -> None:
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT store_name, CASE WHEN actual_revenue < net_revenue_target "
            "THEN 'below' ELSE 'ok' END AS status FROM store_metrics",
            "\u627e\u51fa\u672a\u5b8c\u6210\u5f53\u6708\u51c0\u6536\u5165\u76ee\u6807\u7684\u5e97\u94fa",
            self.graph,
        )
        self.assertIn("\u7b5b\u9009\u6761\u4ef6\u7f3a\u5931", error or "")

    def test_find_below_target_accepts_where_comparison(self) -> None:
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT store_name, actual_revenue, net_revenue_target "
            "FROM store_metrics WHERE actual_revenue < net_revenue_target",
            "\u627e\u51fa\u672a\u5b8c\u6210\u5f53\u6708\u51c0\u6536\u5165\u76ee\u6807\u7684\u5e97\u94fa",
            self.graph,
        )
        self.assertIsNone(error)

    def test_find_below_target_requires_target_in_result_columns(self) -> None:
        error = SingleDatabaseAgent._sql_contract_error(
            "SELECT store_name, actual_revenue FROM store_metrics "
            "WHERE actual_revenue < net_revenue_target",
            "\u627e\u51fa\u672a\u5b8c\u6210\u5f53\u6708\u51c0\u6536\u5165\u76ee\u6807\u7684\u5e97\u94fa",
            self.graph,
        )
        self.assertIn("\u5c55\u793a\u5b57\u6bb5\u7f3a\u5931", error or "")

    def test_result_contract_requires_below_target_filter(self) -> None:
        contract = SingleDatabaseAgent._result_contract(
            "\u627e\u51fa\u672a\u5b8c\u6210\u5f53\u6708\u51c0\u6536\u5165\u76ee\u6807\u7684\u5e97\u94fa",
            self.graph,
        )
        self.assertIn("WHERE", contract["required_filter"])
        self.assertEqual(
            contract["required_evidence_columns"], ["actual_value", "target_value"]
        )

    def test_unique_schema_field_makes_field_clarification_redundant(self) -> None:
        clarification = {
            "parameter": "date_field",
            "question": "用于标识统计日期的字段名称是什么？",
            "reason": "需要确认字段",
            "options": [
                {"id": "stat_date", "label": "stat_date"},
                {"id": "date", "label": "date"},
                {"id": "report_date", "label": "report_date"},
            ],
        }
        resolved = SingleDatabaseAgent._resolve_redundant_field_clarification(
            clarification, self.graph
        )
        self.assertEqual(resolved, "stat_date")

    def test_ambiguous_schema_fields_still_require_clarification(self) -> None:
        clarification = {
            "parameter": "date_field",
            "question": "请选择日期字段",
            "options": [
                {"id": "created_at", "label": "created_at"},
                {"id": "paid_at", "label": "paid_at"},
            ],
        }
        graph = {"fields": [{"name": "created_at"}, {"name": "paid_at"}]}
        resolved = SingleDatabaseAgent._resolve_redundant_field_clarification(
            clarification, graph
        )
        self.assertIsNone(resolved)

    def test_declared_join_clarification_is_redundant(self) -> None:
        clarification = {
            "parameter": "join_permission",
            "question": (
                "是否允许使用 daily_product_metrics.product_id = "
                "products.product_id 进行关联？"
            ),
            "reason": "需要确认关联关系",
            "options": [
                {"id": "allow", "label": "允许直接关联"},
                {"id": "stop", "label": "终止查询"},
            ],
        }
        resolved = SingleDatabaseAgent._resolve_redundant_join_clarification(
            clarification, self.graph
        )
        self.assertEqual(
            resolved,
            "daily_product_metrics.product_id = products.product_id",
        )

    def test_undeclared_join_still_requires_clarification(self) -> None:
        clarification = {
            "parameter": "join_permission",
            "question": "是否允许使用 daily_product_metrics.store_id = products.store_id？",
            "reason": "需要确认关联关系",
            "options": [
                {"id": "allow", "label": "允许"},
                {"id": "stop", "label": "终止"},
            ],
        }
        resolved = SingleDatabaseAgent._resolve_redundant_join_clarification(
            clarification, self.graph
        )
        self.assertIsNone(resolved)

    def test_direct_sql_response_is_normalized_to_tool_call(self) -> None:
        decision = SingleDatabaseAgent._normalize_decision(
            {"sql": "SELECT 1", "reason": "直接查询"},
            "query_ecommerce_ops",
        )
        self.assertEqual(decision["action"], "call_tool")
        self.assertEqual(decision["tool_name"], "query_ecommerce_ops")
        self.assertEqual(decision["arguments"], {"sql": "SELECT 1"})

    def test_tool_payload_without_action_is_normalized(self) -> None:
        decision = SingleDatabaseAgent._normalize_decision(
            {
                "tool_name": "query_ecommerce_ops",
                "arguments": {"sql": "SELECT 1"},
            },
            "query_ecommerce_ops",
        )
        self.assertEqual(decision["action"], "call_tool")


if __name__ == "__main__":
    unittest.main()
