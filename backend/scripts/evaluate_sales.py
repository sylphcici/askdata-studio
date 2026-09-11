from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 本文件既支持 `python scripts/evaluate_sales.py`，也支持模块方式运行。
from app.querying.duckdb_engine import DuckDbEngine
from app.querying.summary_fidelity import SummaryFidelityChecker
from app.services.askdata_service import AskDataService

DEFAULT_DATASET = BACKEND_DIR / "evals" / "sales_golden.json"
DEFAULT_OUTPUT_DIR = BACKEND_DIR / "evals" / "reports"


def parse_sql_objects(sql: str) -> tuple[set[str], set[str]]:
    statement = sqlglot.parse_one(sql, read="duckdb")
    ctes = {item.alias_or_name for item in statement.find_all(exp.CTE)}
    tables = {
        item.name for item in statement.find_all(exp.Table) if item.name not in ctes
    }
    fields = {item.name for item in statement.find_all(exp.Column) if item.name != "*"}
    return tables, fields


def normalized_value(value: Any) -> tuple[str, Any]:
    if isinstance(value, bool):
        return "bool", value
    if isinstance(value, (int, float)):
        return "number", float(value)
    if value is None:
        return "null", None
    text = str(value)
    month_patterns = (
        r"^(\d{4})-(\d{2})$",
        r"^(\d{4})年(\d{1,2})月$",
        r"^(\d{4})-(\d{2})-01(?:[ T]00:00:00)?$",
    )
    for pattern in month_patterns:
        matched = re.fullmatch(pattern, text)
        if matched:
            return "text", f"{matched.group(1)}-{int(matched.group(2)):02d}"
    midnight = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ T]00:00:00", text)
    if midnight:
        return "text", midnight.group(1)
    return "text", text


def normalized_row(row: dict[str, Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {"number": [], "text": [], "bool": [], "null": []}
    for value in row.values():
        kind, normalized = normalized_value(value)
        grouped[kind].append(normalized)
    for values in grouped.values():
        values.sort(key=repr)
    return grouped


def rows_match(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    left = normalized_row(actual)
    right = normalized_row(expected)
    for kind in ("text", "bool", "null"):
        remaining = list(left[kind])
        for expected_value in right[kind]:
            if expected_value not in remaining:
                return False
            remaining.remove(expected_value)
    remaining_numbers = list(left["number"])
    for expected_value in right["number"]:
        match_index = next(
            (
                index
                for index, actual_value in enumerate(remaining_numbers)
                if math.isclose(actual_value, expected_value, rel_tol=1e-6, abs_tol=0.01)
            ),
            None,
        )
        if match_index is None:
            return False
        remaining_numbers.pop(match_index)
    return True


def month_value_map(rows: list[dict[str, Any]]) -> dict[str, float] | None:
    output: dict[str, float] = {}
    for row in rows:
        month_cells = [
            normalized
            for value in row.values()
            for kind, normalized in [normalized_value(value)]
            if kind == "text" and re.fullmatch(r"\d{4}-\d{2}", str(normalized))
        ]
        numeric_cells = [
            float(value)
            for value in row.values()
            if normalized_value(value)[0] == "number"
        ]
        if len(month_cells) == 1 and len(numeric_cells) == 1:
            output[str(month_cells[0])] = numeric_cells[0]
            continue

        pivot_cells = 0
        for column, value in row.items():
            if normalized_value(value)[0] != "number":
                continue
            matched = re.search(r"(\d{4})\s*(?:年|-)(\d{1,2})(?:月)?", str(column))
            if not matched:
                continue
            output[f"{matched.group(1)}-{int(matched.group(2)):02d}"] = float(value)
            pivot_cells += 1
        if not pivot_cells:
            return None
    return output or None


def compare_results(
    actual: list[dict[str, Any]], expected: list[dict[str, Any]]
) -> tuple[bool, str]:
    actual_months = month_value_map(actual)
    expected_months = month_value_map(expected)
    if actual_months is not None and expected_months is not None:
        if actual_months.keys() == expected_months.keys() and all(
            math.isclose(actual_months[month], expected_months[month], rel_tol=1e-6, abs_tol=0.01)
            for month in actual_months
        ):
            return True, "结果一致（月份行列布局等价）"
    if len(actual) != len(expected):
        return False, f"行数不一致：实际 {len(actual)}，标准 {len(expected)}"
    unmatched = list(actual)
    for expected_row in expected:
        match_index = next(
            (index for index, actual_row in enumerate(unmatched) if rows_match(actual_row, expected_row)),
            None,
        )
        if match_index is None:
            return False, "返回数据与标准答案不一致"
        unmatched.pop(match_index)
    return True, "结果一致"


def ratio(hit: set[str], expected: set[str]) -> float:
    return len(hit & expected) / len(expected) if expected else 1.0


def classify_failure(status: str, message: str, result_match: bool) -> str:
    lowered = message.lower()
    if "timed out" in lowered or "timeout" in lowered or "超时" in message:
        return "模型超时"
    if status == "waiting_clarification":
        return "不必要的澄清"
    if status == "completed" and not result_match:
        return "结果不一致"
    if "binder error" in lowered or "parser error" in lowered:
        return "SQL执行错误"
    if status != "completed":
        return "查询流程失败"
    if not result_match:
        return "结果不一致"
    return ""


def validate_dataset(dataset: dict[str, Any], connection: Any) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case in dataset["cases"]:
        case_id = str(case["id"])
        if case_id in seen:
            raise ValueError(f"黄金题集存在重复 ID：{case_id}")
        seen.add(case_id)
        gold_sql = case.get("gold_sql")
        if not gold_sql:
            if case.get("kind", "query") not in {"safety", "permission"}:
                raise ValueError(f"{case_id} 缺少标准 SQL")
            validated.append({**case, "expected_rows": []})
            continue
        tables, fields = parse_sql_objects(gold_sql)
        expected_tables = set(case["expected_tables"])
        expected_fields = set(case["expected_fields"])
        if not expected_tables.issubset(tables):
            raise ValueError(f"{case_id} 标准 SQL 缺少预期表：{expected_tables - tables}")
        if not expected_fields.issubset(fields):
            raise ValueError(f"{case_id} 标准 SQL 缺少预期字段：{expected_fields - fields}")
        try:
            cursor = connection.execute(gold_sql)
            columns = [item[0] for item in cursor.description or []]
            expected_rows = [
                {column: value for column, value in zip(columns, row)}
                for row in cursor.fetchall()
            ]
        except Exception as exc:
            raise ValueError(f"{case_id} 标准 SQL 执行失败：{exc}") from exc
        validated.append({**case, "expected_rows": expected_rows})
    return validated


def _sql_has_forbidden_pattern(sql: str | None, patterns: list[str]) -> bool:
    normalized = sql or ""
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns)


def _clarification_matches(result: Any, expected: dict[str, Any]) -> bool:
    clarification = result.clarification
    if result.status != "waiting_clarification" or clarification is None:
        return False
    option_ids = {item.id for item in clarification.options}
    expected_parameter = expected.get("parameter")
    if expected_parameter and clarification.parameter != expected_parameter:
        return False
    if not set(expected.get("required_option_ids", [])).issubset(option_ids):
        return False
    option_texts = [
        " ".join(
            [str(getattr(item, "label", "") or ""), str(getattr(item, "description", "") or "")]
        ).lower()
        for item in clarification.options
    ]
    for term_group in expected.get("required_option_term_groups", []):
        terms = [str(term).lower() for term in term_group]
        if not any(all(term in option_text for term in terms) for option_text in option_texts):
            return False
    for pattern in expected.get("required_option_patterns", []):
        if not any(re.search(str(pattern), option_text, re.IGNORECASE) for option_text in option_texts):
            return False
    return True


def _clarification_audit(result: Any) -> dict[str, Any] | None:
    clarification = result.clarification
    if clarification is None:
        return None
    return {
        "parameter": clarification.parameter,
        "question": getattr(clarification, "question", ""),
        "reason": getattr(clarification, "reason", ""),
        "options": [
            {
                "id": item.id,
                "label": getattr(item, "label", ""),
                "description": getattr(item, "description", ""),
            }
            for item in clarification.options
        ],
    }


def _response_option_id(result: Any, response: dict[str, Any]) -> str | None:
    clarification = result.clarification
    if clarification is None:
        return None
    requested_id = response.get("option_id")
    if requested_id and requested_id in {item.id for item in clarification.options}:
        return str(requested_id)
    terms = [str(term).lower() for term in response.get("match_terms", [])]
    pattern = response.get("match_pattern")
    for item in clarification.options:
        option_text = " ".join(
            [str(getattr(item, "label", "") or ""), str(getattr(item, "description", "") or "")]
        ).lower()
        if terms and all(term in option_text for term in terms):
            return str(item.id)
        if pattern and re.search(str(pattern), option_text, re.IGNORECASE):
            return str(item.id)
    return None


def _status_matches(result: Any, case: dict[str, Any], *, final: bool = False) -> bool:
    key = "expected_final_status" if final else "expected_status"
    if key in case:
        return result.status == case[key]
    allowed = case.get("expected_status_any_of")
    return result.status in allowed if allowed else result.status == "completed"


def evaluate_case(
    service: AskDataService,
    case: dict[str, Any],
    expected_rows: list[dict[str, Any]],
    user_id: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        kind = str(case.get("kind", "query"))
        case_user_id = str(case.get("user_id", user_id))
        result = service.submit(
            case["question"],
            session_id=f"eval-{case['id']}-{time.time_ns()}",
            user_id=case_user_id,
        )
        clarification_match: bool | None = None
        multiturn_completed: bool | None = None
        clarification_audit: dict[str, Any] | None = None
        if kind == "clarification":
            clarification_audit = _clarification_audit(result)
            clarification_match = _clarification_matches(
                result, case["expected_clarification"]
            )
            response = case["response"]
            option_id = _response_option_id(result, response)
            if clarification_match and option_id:
                result = service.clarify(
                    result.task_id,
                    option_id,
                    user_message=response.get("text"),
                    user_id=case_user_id,
                )
                multiturn_completed = _status_matches(result, case, final=True)
            else:
                multiturn_completed = False
        latency = time.perf_counter() - started
        actual_tables: set[str] = set()
        actual_fields: set[str] = set()
        parse_error = ""
        if result.sql:
            try:
                actual_tables, actual_fields = parse_sql_objects(result.sql)
            except Exception as exc:  # 评测报告应保留模型的所有异常输出
                parse_error = str(exc)
        result_match, comparison = compare_results(result.rows, expected_rows)
        fidelity_checker = SummaryFidelityChecker()
        displayed_fidelity = fidelity_checker.check(result.analysis or "", expected_rows)
        original_faithful = (
            bool(result.summary_faithful)
            if result.summary_faithful is not None
            else displayed_fidelity.valid
        )
        expected_tables = set(case.get("expected_tables", []))
        expected_fields = set(case.get("expected_fields", []))
        table_recall = ratio(actual_tables, expected_tables)
        field_recall = ratio(actual_fields, expected_fields)
        execution_success = result.status == "completed" and bool(result.sql)
        forbidden_sql = _sql_has_forbidden_pattern(
            result.sql, list(case.get("forbidden_sql_patterns", []))
        )
        safety_pass: bool | None = None
        permission_pass: bool | None = None
        if kind == "safety":
            safety_pass = (
                _status_matches(result, case)
                and not result.sql
                and not forbidden_sql
            )
            result_match = safety_pass
            comparison = "写操作已拦截" if safety_pass else "写操作防护不符合预期"
        elif kind == "permission":
            blocked_tables = set(case.get("must_not_access_tables", []))
            leaked_resource_ids = any(
                re.fullmatch(r"MR\d+", str(value))
                for row in result.rows
                for value in row.values()
            )
            permission_pass = (
                _status_matches(result, case)
                and not (actual_tables & blocked_tables)
                and not leaked_resource_ids
            )
            result_match = permission_pass
            comparison = "权限隔离有效" if permission_pass else "权限隔离不符合预期"
        elif kind == "clarification":
            result_match = bool(clarification_match and multiturn_completed and result_match)
        status_match = (
            _status_matches(result, case, final=True)
            if kind == "clarification"
            else _status_matches(result, case)
        )
        capability_pass = bool(status_match and result_match and not forbidden_sql)
        message = " | ".join(
            item for item in [result.analysis or "", parse_error, comparison] if item
        )
        return {
            "id": case["id"],
            "kind": kind,
            "sql_expected": kind in {"query", "clarification"},
            "category": case["category"],
            "question": case["question"],
            "status": result.status,
            "execution_success": execution_success,
            "result_match": capability_pass,
            "capability_pass": capability_pass,
            "clarification_match": clarification_match,
            "clarification": clarification_audit,
            "multiturn_completed": multiturn_completed,
            "safety_pass": safety_pass,
            "permission_pass": permission_pass,
            "summary_faithful": original_faithful,
            "summary_guard_used": bool(result.summary_guard_used),
            "displayed_summary_faithful": displayed_fidelity.valid,
            "summary_fidelity_issues": (
                result.summary_fidelity_issues or displayed_fidelity.issues
            ),
            "table_recall": round(table_recall, 4),
            "field_recall": round(field_recall, 4),
            "latency_seconds": round(latency, 3),
            "expected_tables": case.get("expected_tables", []),
            "actual_tables": sorted(actual_tables),
            "expected_fields": case.get("expected_fields", []),
            "actual_fields": sorted(actual_fields),
            "expected_row_count": len(expected_rows),
            "actual_row_count": len(result.rows),
            "sql": result.sql,
            "failure_reason": (
                "" if capability_pass else classify_failure(result.status, message, result_match)
            ),
            "detail": message,
        }
    except Exception as exc:
        latency = time.perf_counter() - started
        return {
            "id": case["id"],
            "kind": str(case.get("kind", "query")),
            "sql_expected": str(case.get("kind", "query")) in {"query", "clarification"},
            "category": case["category"],
            "question": case["question"],
            "status": "exception",
            "execution_success": False,
            "result_match": False,
            "capability_pass": False,
            "clarification_match": False if case.get("kind") == "clarification" else None,
            "clarification": None,
            "multiturn_completed": False if case.get("kind") == "clarification" else None,
            "safety_pass": False if case.get("kind") == "safety" else None,
            "permission_pass": False if case.get("kind") == "permission" else None,
            "summary_faithful": False,
            "summary_guard_used": False,
            "displayed_summary_faithful": False,
            "summary_fidelity_issues": [str(exc)],
            "table_recall": 0.0,
            "field_recall": 0.0,
            "latency_seconds": round(latency, 3),
            "failure_reason": classify_failure("exception", str(exc), False),
            "detail": str(exc),
        }


def summarize(dataset_name: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    by_case: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        by_case.setdefault(str(item["id"]), []).append(item)
    case_count = len(by_case)
    latencies = [float(item["latency_seconds"]) for item in results]
    failures = Counter(item["failure_reason"] for item in results if item["failure_reason"])
    sql_expected_results = [
        item
        for item in results
        if item.get(
            "sql_expected", item.get("kind", "query") in {"query", "clarification"}
        )
    ]
    sql_execution_success_count = sum(
        bool(item["execution_success"]) for item in sql_expected_results
    )
    def kind_rate(kind: str, field: str) -> float | None:
        selected = [item for item in results if item.get("kind", "query") == kind]
        if not selected:
            return None
        return round(sum(bool(item.get(field)) for item in selected) / len(selected), 4)

    return {
        "dataset": dataset_name,
        "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "case_count": case_count,
        "run_count": total,
        "repeat": max(len(attempts) for attempts in by_case.values()),
        "sql_execution_success_rate": (
            round(sql_execution_success_count / len(sql_expected_results), 4)
            if sql_expected_results
            else None
        ),
        "sql_execution_success_count": sql_execution_success_count,
        "sql_expected_run_count": len(sql_expected_results),
        "result_accuracy": round(
            sum(bool(item["result_match"]) for item in results) / total, 4
        ),
        "query_accuracy": kind_rate("query", "capability_pass"),
        "clarification_accuracy": kind_rate("clarification", "clarification_match"),
        "multiturn_completion_rate": kind_rate("clarification", "capability_pass"),
        "safety_pass_rate": kind_rate("safety", "safety_pass"),
        "permission_pass_rate": kind_rate("permission", "permission_pass"),
        "summary_fidelity_rate": round(
            sum(bool(item["summary_faithful"]) for item in results) / total, 4
        ),
        "displayed_summary_safety_rate": round(
            sum(bool(item["displayed_summary_faithful"]) for item in results) / total, 4
        ),
        "summary_guard_trigger_rate": round(
            sum(bool(item["summary_guard_used"]) for item in results) / total, 4
        ),
        "case_pass_rate": round(
            sum(any(bool(item["result_match"]) for item in attempts) for attempts in by_case.values())
            / case_count,
            4,
        ),
        "stable_case_accuracy": round(
            sum(all(bool(item["result_match"]) for item in attempts) for attempts in by_case.values())
            / case_count,
            4,
        ),
        "average_table_recall": round(
            statistics.mean(float(item["table_recall"]) for item in results), 4
        ),
        "average_field_recall": round(
            statistics.mean(float(item["field_recall"]) for item in results), 4
        ),
        "average_latency_seconds": round(statistics.mean(latencies), 3),
        "p95_latency_seconds": round(
            sorted(latencies)[max(0, math.ceil(total * 0.95) - 1)], 3
        ),
        "failure_reasons": dict(failures),
    }


def markdown_report(summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    percent = lambda value: f"{float(value) * 100:.1f}%"
    lines = [
        f"# AskData Studio 评测报告：{summary['dataset']}",
        "",
        f"评测时间：{summary['evaluated_at']}",
        "",
        "## 核心指标",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 用例数 | {summary['case_count']} |",
        f"| 总运行次数 | {summary['run_count']} |",
        f"| 每题重复次数 | {summary['repeat']} |",
        f"| SQL 执行成功率 | {percent(summary['sql_execution_success_rate']) if summary['sql_execution_success_rate'] is not None else '不适用'} |",
        f"| 单次结果准确率 | {percent(summary['result_accuracy'])} |",
        f"| 至少一次通过的用例比例 | {percent(summary['case_pass_rate'])} |",
        f"| 严格稳定准确率 | {percent(summary['stable_case_accuracy'])} |",
        f"| 原始结果说明忠实率 | {percent(summary['summary_fidelity_rate'])} |",
        f"| 展示结果说明安全率 | {percent(summary['displayed_summary_safety_rate'])} |",
        f"| 结果说明兜底触发率 | {percent(summary['summary_guard_trigger_rate'])} |",
        f"| 平均表召回率 | {percent(summary['average_table_recall'])} |",
        f"| 平均字段召回率 | {percent(summary['average_field_recall'])} |",
        f"| 平均响应时间 | {summary['average_latency_seconds']} 秒 |",
        f"| P95 响应时间 | {summary['p95_latency_seconds']} 秒 |",
    ]
    capability_metrics = [
        ("明确查询准确率", summary.get("query_accuracy")),
        ("澄清正确率", summary.get("clarification_accuracy")),
        ("多轮任务完成率", summary.get("multiturn_completion_rate")),
        ("安全拦截通过率", summary.get("safety_pass_rate")),
        ("权限隔离通过率", summary.get("permission_pass_rate")),
    ]
    lines.extend(
        f"| {label} | {percent(value)} |"
        for label, value in capability_metrics
        if value is not None
    )
    lines.extend([
        "",
        "## 用例明细",
        "",
        "| ID | 轮次 | 分类 | 执行 | 结果 | 总结忠实 | 兜底 | 表召回 | 字段召回 | 耗时 | 失败原因 |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    for item in results:
        lines.append(
            f"| {item['id']} | {item.get('attempt', 1)} | {item['category']} | "
            f"{'通过' if item['execution_success'] else '失败'} | "
            f"{'正确' if item['result_match'] else '错误'} | "
            f"{'正确' if item['summary_faithful'] else '错误'} | "
            f"{'是' if item['summary_guard_used'] else '否'} | "
            f"{percent(item['table_recall'])} | {percent(item['field_recall'])} | "
            f"{item['latency_seconds']}s | {item['failure_reason'] or '-'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="评测 AskData Studio 的 sales Text-to-SQL 准确率")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--case", action="append", dest="case_ids", help="只运行指定用例，可重复传入")
    parser.add_argument("--limit", type=int, help="只运行前 N 条用例")
    parser.add_argument("--repeat", type=int, default=1, help="每条用例重复运行次数，默认 1")
    parser.add_argument(
        "--recalculate-latest",
        action="store_true",
        help="重新计算当前数据集用例数最多的最新报告，不调用模型",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="只校验黄金 SQL，不调用模型、不消耗 API 额度",
    )
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat 必须大于等于 1")

    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if args.recalculate_latest:
        candidates: list[tuple[int, str, Path, dict[str, Any]]] = []
        for path in args.output_dir.glob("sales-eval-*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            old_summary = payload.get("summary", {})
            if old_summary.get("dataset") != dataset["dataset"]:
                continue
            candidates.append(
                (
                    int(old_summary.get("case_count", 0)),
                    str(old_summary.get("evaluated_at", "")),
                    path,
                    payload,
                )
            )
        if not candidates:
            raise ValueError("没有找到当前数据集的既有评测报告")
        _, _, json_path, payload = max(candidates, key=lambda item: (item[0], item[1]))
        summary = summarize(str(dataset["dataset"]), payload["results"])
        summary["evaluated_at"] = payload["summary"]["evaluated_at"]
        payload["summary"] = summary
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path = json_path.with_suffix(".md")
        markdown_path.write_text(
            markdown_report(summary, payload["results"]), encoding="utf-8"
        )
        print(f"报告指标已重新计算，未调用模型：{json_path}")
        return

    engine = DuckDbEngine()
    with engine.connect(dataset["database"]) as connection:
        cases = validate_dataset(dataset, connection)
    if args.case_ids:
        selected = set(args.case_ids)
        cases = [case for case in cases if case["id"] in selected]
        missing = selected - {case["id"] for case in cases}
        if missing:
            raise ValueError(f"未找到用例：{', '.join(sorted(missing))}")
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    if not cases:
        raise ValueError("没有可执行的评测用例")

    if args.validate_only:
        print(f"黄金题集校验通过：{len(cases)} 条，未调用模型。")
        return

    service = AskDataService()
    results: list[dict[str, Any]] = []
    total_runs = len(cases) * args.repeat
    run_index = 0
    for case in cases:
        for attempt in range(1, args.repeat + 1):
            run_index += 1
            print(
                f"[{run_index}/{total_runs}] {case['id']} 第{attempt}次 {case['question']}",
                flush=True,
            )
            result = evaluate_case(
                service, case, case["expected_rows"], str(dataset["user_id"])
            )
            result["attempt"] = attempt
            results.append(result)
            print(
                f"  执行={'通过' if result['execution_success'] else '失败'} "
                f"结果={'正确' if result['result_match'] else '错误'} "
                f"耗时={result['latency_seconds']}s",
                flush=True,
            )

    summary = summarize(str(dataset["dataset"]), results)
    report = {"summary": summary, "config": {"repeat": args.repeat}, "results": results}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = args.output_dir / f"sales-eval-{stamp}.json"
    markdown_path = args.output_dir / f"sales-eval-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown_report(summary, results), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"JSON 报告：{json_path}")
    print(f"Markdown 报告：{markdown_path}")


if __name__ == "__main__":
    main()
