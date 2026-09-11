from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


REPORTS_DIR = Path(__file__).resolve().parents[2] / "evals" / "reports"
REPORT_ID_PATTERN = re.compile(r"sales-eval-\d{8}-\d{6}")


class EvaluationReportService:
    """只读访问本地评测报告，不负责触发会产生费用的评测任务。"""

    def __init__(self, reports_dir: Path | None = None) -> None:
        self.reports_dir = reports_dir or REPORTS_DIR

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self.reports_dir.exists():
            return reports
        for path in sorted(
            self.reports_dir.glob("sales-eval-*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            try:
                payload = self._read(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            summary = dict(payload.get("summary") or {})
            reports.append({
                "id": path.stem,
                "evaluated_at": summary.get("evaluated_at"),
                "case_count": int(summary.get("case_count") or 0),
                "run_count": int(summary.get("run_count") or 0),
                "repeat": int((payload.get("config") or {}).get("repeat") or 1),
                "result_accuracy": float(summary.get("result_accuracy") or 0),
                "sql_execution_success_rate": float(
                    summary.get("sql_execution_success_rate") or 0
                ),
                "displayed_summary_safety_rate": float(
                    summary.get("displayed_summary_safety_rate") or 0
                ),
                "average_latency_seconds": float(
                    summary.get("average_latency_seconds") or 0
                ),
                "p95_latency_seconds": float(summary.get("p95_latency_seconds") or 0),
                "is_full": int(summary.get("case_count") or 0) >= 20,
            })
        return reports

    def get_report(self, report_id: str) -> dict[str, Any]:
        if not REPORT_ID_PATTERN.fullmatch(report_id):
            raise KeyError(report_id)
        path = self.reports_dir / f"{report_id}.json"
        if not path.is_file():
            raise KeyError(report_id)
        payload = self._read(path)
        return {"id": report_id, **payload}

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("评测报告格式错误")
        return payload
