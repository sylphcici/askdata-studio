from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("ASKDATA_SALES_PASSWORD", "test-sales-password")

from fastapi.testclient import TestClient

from app.api.routes import service
from app.main import app
from app.models import QueryResult
from app.querying.duckdb_engine import DuckDbEngine
from app.services.excel_export import build_excel_xml


class FullExportTest(unittest.TestCase):
    def test_preview_reports_total_and_full_query_returns_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "demo"
            database.mkdir()
            rows = "id,name\n" + "\n".join(f"{index},item-{index}" for index in range(308))
            (database / "items.csv").write_text(rows, encoding="utf-8")
            engine = DuckDbEngine(Path(temp_dir))

            schema = [{"id": "items", "name": "items", "database": "demo"}]
            with patch("app.querying.duckdb_engine.SCHEMA", schema):
                preview = engine.execute("demo", "SELECT id, name FROM items")
                complete = engine.execute_full("demo", "SELECT id, name FROM items")

            self.assertTrue(preview.success)
            self.assertEqual(len(preview.rows), 200)
            self.assertEqual(preview.total_row_count, 308)
            self.assertTrue(preview.truncated)
            self.assertEqual(len(complete.rows), 308)
            self.assertFalse(complete.truncated)

    def test_excel_contains_every_exported_row(self) -> None:
        rows = [{"地区": "华东", "金额": index} for index in range(308)]
        content = build_excel_xml("完整结果", ["地区", "金额"], rows)
        text = content.decode("utf-8-sig")
        self.assertIn("完整导出 · 共 308 行", text)
        self.assertIn(">307</Data>", text)

    def test_export_endpoint_returns_owner_full_workbook(self) -> None:
        task_id = "export-test-task"
        result = QueryResult(
            task_id=task_id,
            status="completed",
            route="database_query",
            message="查询完成",
            sql="SELECT region, paid_amount FROM orders",
            columns=["region", "paid_amount"],
            rows=[],
            result_title="完整导出测试",
            tool_calls=[{"database": "ecommerce_ops", "success": True}],
        )
        service.tasks[task_id] = {
            "user_id": "demo_current_sales",
            "result": result,
        }
        try:
            with TestClient(app) as client:
                token = client.post(
                    "/api/auth/login",
                    json={"username": "sales", "password": "test-sales-password"},
                ).json()["access_token"]
                response = client.get(
                    f"/api/tasks/{task_id}/export",
                    headers={"Authorization": f"Bearer {token}"},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"].split(";", 1)[0], "application/vnd.ms-excel")
            self.assertIn(b"<Workbook", response.content)
        finally:
            service.tasks.pop(task_id, None)


if __name__ == "__main__":
    unittest.main()
