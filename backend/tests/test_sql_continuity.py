import unittest

from app.querying.sql_continuity import SqlContinuityGuard


PREVIOUS_SQL = """
SELECT region AS 地区, SUM(paid_amount) AS 实付销售额
FROM orders
WHERE ordered_at >= DATE '2026-07-01'
  AND ordered_at < DATE '2026-08-01'
GROUP BY region
"""


class SqlContinuityGuardTest(unittest.TestCase):
    def test_classifies_supported_follow_up_operations(self) -> None:
        self.assertEqual(SqlContinuityGuard.classify("只看华东和华南"), "filter_change")
        self.assertEqual(SqlContinuityGuard.classify("换成6月"), "time_change")
        self.assertEqual(SqlContinuityGuard.classify("再按店铺拆分"), "dimension_change")
        self.assertEqual(SqlContinuityGuard.classify("换成订单量"), "metric_change")

    def test_filter_can_change_without_changing_query_scope(self) -> None:
        current = """
        SELECT region AS 地区, SUM(paid_amount) AS 实付销售额
        FROM orders
        WHERE ordered_at >= DATE '2026-07-01'
          AND ordered_at < DATE '2026-08-01'
          AND region IN ('华东', '华南')
        GROUP BY region
        """
        self.assertIsNone(
            SqlContinuityGuard.validate(PREVIOUS_SQL, current, "filter_change")
        )

    def test_filter_change_rejects_metric_drift(self) -> None:
        drifted = PREVIOUS_SQL.replace("SUM(paid_amount)", "SUM(payable_amount)")
        error = SqlContinuityGuard.validate(PREVIOUS_SQL, drifted, "filter_change")
        self.assertIn("指标及聚合方式", error or "")

    def test_time_change_allows_dates_but_not_metric(self) -> None:
        june = PREVIOUS_SQL.replace("2026-07-01", "2026-06-01").replace(
            "2026-08-01", "2026-07-01"
        )
        self.assertIsNone(SqlContinuityGuard.validate(PREVIOUS_SQL, june, "time_change"))
        drifted = june.replace("SUM(paid_amount)", "SUM(payable_amount)")
        self.assertIn(
            "指标及聚合方式",
            SqlContinuityGuard.validate(PREVIOUS_SQL, drifted, "time_change") or "",
        )

    def test_time_change_rejects_switch_from_order_time_to_payment_time(self) -> None:
        drifted = """
        SELECT o.region AS 大区, SUM(o.paid_amount) AS 实付销售额
        FROM orders o JOIN payments p ON o.order_id = p.order_id
        WHERE p.paid_at >= '2026-06-01'
          AND p.paid_at < '2026-07-01'
          AND o.region IN ('华东', '华南')
        GROUP BY o.region
        """
        error = SqlContinuityGuard.validate(PREVIOUS_SQL, drifted, "time_change")
        self.assertIn("时间字段", error or "")
        self.assertIn("数据表", error or "")

    def test_dimension_change_keeps_metric_and_time(self) -> None:
        by_store = """
        SELECT s.store_name, SUM(o.paid_amount)
        FROM orders o JOIN stores s ON o.store_id = s.store_id
        WHERE o.ordered_at >= DATE '2026-07-01'
          AND o.ordered_at < DATE '2026-08-01'
        GROUP BY s.store_name
        """
        self.assertIsNone(
            SqlContinuityGuard.validate(PREVIOUS_SQL, by_store, "dimension_change")
        )

    def test_dimension_change_must_keep_existing_region_filter_and_source(self) -> None:
        filtered = PREVIOUS_SQL.replace(
            "GROUP BY region",
            "AND region IN ('华东', '华南') GROUP BY region",
        )
        dropped_filter = """
        SELECT s.store_name, SUM(o.paid_amount)
        FROM orders o JOIN stores s ON o.store_id = s.store_id
        WHERE o.ordered_at >= DATE '2026-07-01'
          AND o.ordered_at < DATE '2026-08-01'
        GROUP BY s.store_name
        """
        error = SqlContinuityGuard.validate(filtered, dropped_filter, "dimension_change")
        self.assertIn("既有筛选条件", error or "")

        wrong_region_source = dropped_filter.replace(
            "GROUP BY s.store_name",
            "AND s.region IN ('华东', '华南') GROUP BY s.store_name",
        )
        error = SqlContinuityGuard.validate(filtered, wrong_region_source, "dimension_change")
        self.assertIn("既有筛选条件", error or "")

        preserved = dropped_filter.replace(
            "GROUP BY s.store_name",
            "AND o.region IN ('华东', '华南') GROUP BY s.store_name",
        )
        self.assertIsNone(
            SqlContinuityGuard.validate(filtered, preserved, "dimension_change")
        )

    def test_clear_region_filter_keeps_grouping_metric_and_time(self) -> None:
        filtered = """
        SELECT s.store_name, o.region, SUM(o.paid_amount)
        FROM orders o JOIN stores s ON o.store_id = s.store_id
        WHERE o.ordered_at >= DATE '2026-06-01'
          AND o.ordered_at < DATE '2026-07-01'
          AND o.region IN ('华东', '华南')
        GROUP BY s.store_name, o.region
        """
        rewritten = SqlContinuityGuard.clear_filter_sql(filtered, "不限制地区")
        self.assertIsNotNone(rewritten)
        self.assertNotIn("IN ('华东', '华南')", rewritten or "")
        self.assertIn("GROUP BY s.store_name, o.region", rewritten or "")
        self.assertIn("SUM(o.paid_amount)", rewritten or "")
        self.assertIn("2026-06-01", rewritten or "")


if __name__ == "__main__":
    unittest.main()
