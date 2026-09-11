from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.services.evaluation_reports import EvaluationReportService


class EvaluationReportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.reports_dir = Path(self.temp_dir.name)
        self.service = EvaluationReportService(self.reports_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_report(self, name: str, case_count: int, accuracy: float) -> None:
        payload = {
            "summary": {
                "evaluated_at": "2026-09-05T03:37:17+08:00",
                "case_count": case_count,
                "run_count": case_count,
                "result_accuracy": accuracy,
                "sql_execution_success_rate": accuracy,
                "displayed_summary_safety_rate": 1.0,
                "average_latency_seconds": 19.9,
                "p95_latency_seconds": 27.7,
            },
            "config": {"repeat": 1},
            "results": [],
        }
        (self.reports_dir / f"{name}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_lists_report_summaries_and_marks_full_runs(self) -> None:
        self.write_report("sales-eval-20260905-033717", 20, 0.95)
        self.write_report("sales-eval-20260905-032419", 1, 1.0)
        reports = self.service.list_reports()
        self.assertEqual(len(reports), 2)
        full = next(item for item in reports if item["case_count"] == 20)
        self.assertTrue(full["is_full"])
        self.assertEqual(full["result_accuracy"], 0.95)

    def test_reads_detail_and_rejects_invalid_identifier(self) -> None:
        report_id = "sales-eval-20260905-033717"
        self.write_report(report_id, 20, 0.95)
        self.assertEqual(self.service.get_report(report_id)["id"], report_id)
        with self.assertRaises(KeyError):
            self.service.get_report("../secret")
