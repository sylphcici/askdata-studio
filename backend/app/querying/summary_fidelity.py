from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


MAX_WORDS = ("最高", "最多", "最大", "居首", "第一")
MIN_WORDS = ("最低", "最少", "最小", "末位")


@dataclass
class FidelityCheck:
    valid: bool
    issues: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)


class SummaryFidelityChecker:
    """用确定性规则校验结果说明中的极值结论，不使用另一个模型裁判。"""

    def build_facts(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"row_count": 0, "dimensions": [], "metrics": [], "extrema": []}
        columns = list(rows[0])
        numeric_columns = [column for column in columns if self._is_numeric_column(rows, column)]
        dimensions = [column for column in columns if column not in numeric_columns]
        extrema: list[dict[str, Any]] = []
        for metric in numeric_columns:
            candidates = [row for row in rows if self._number(row.get(metric)) is not None]
            if not candidates:
                continue
            for kind, chooser in (("max", max), ("min", min)):
                chosen = chooser(candidates, key=lambda row: self._number(row.get(metric)) or 0.0)
                value = chosen.get(metric)
                tied = [
                    row for row in candidates
                    if self._number(row.get(metric)) == self._number(value)
                ]
                extrema.append({
                    "metric": metric,
                    "kind": kind,
                    "value": value,
                    "dimensions": [
                        {dimension: row.get(dimension) for dimension in dimensions}
                        for row in tied[:5]
                    ],
                })
        return {
            "row_count": len(rows),
            "dimensions": dimensions,
            "metrics": numeric_columns,
            "extrema": extrema,
        }

    def check(self, analysis: str, rows: list[dict[str, Any]]) -> FidelityCheck:
        facts = self.build_facts(rows)
        if not analysis or not rows:
            return FidelityCheck(True, facts=facts)
        issues: list[str] = []
        for matched in re.finditer(
            r"(?:共|返回|所有)(?:有|计|包含|统计到)?\s*(\d+)\s*(?:行|条|家|种)",
            analysis,
        ):
            claimed_count = int(matched.group(1))
            if claimed_count != facts["row_count"]:
                issues.append(
                    f"说明声称返回{claimed_count}项，但结果表实际返回{facts['row_count']}行"
                )
        clauses = [item.strip() for item in re.split(r"[。！？；;，,\n]", analysis) if item.strip()]
        known_dimensions = self._dimension_variants(rows, facts["dimensions"])
        for clause in clauses:
            for kind, words in (("max", MAX_WORDS), ("min", MIN_WORDS)):
                if not any(word in clause for word in words):
                    continue
                matching_facts = [
                    item for item in facts["extrema"]
                    if item["kind"] == kind and item["metric"] in clause
                ]
                if not matching_facts and len(facts["metrics"]) == 1:
                    matching_facts = [
                        item for item in facts["extrema"] if item["kind"] == kind
                    ]
                if not matching_facts:
                    continue
                claimed = {variant for variant in known_dimensions if variant and variant in clause}
                if not claimed:
                    continue
                expected: set[str] = set()
                for fact in matching_facts:
                    for dimension_row in fact["dimensions"]:
                        for value in dimension_row.values():
                            expected.update(self._variants(value))
                if not claimed & expected:
                    label = "最高/最多" if kind == "max" else "最低/最少"
                    issues.append(
                        f"“{clause}”中的{label}对象与结果表计算值不一致"
                    )
        return FidelityCheck(not issues, issues, facts)

    def fallback_summary(self, facts: dict[str, Any]) -> str:
        row_count = int(facts.get("row_count") or 0)
        sentences = [f"查询成功，共返回{row_count}行数据。"]
        metrics = list(facts.get("metrics") or [])[:2]
        for metric in metrics:
            maximum = next(
                (item for item in facts["extrema"] if item["metric"] == metric and item["kind"] == "max"),
                None,
            )
            minimum = next(
                (item for item in facts["extrema"] if item["metric"] == metric and item["kind"] == "min"),
                None,
            )
            if not maximum or not minimum:
                continue
            max_context = self._context_text(maximum["dimensions"])
            min_context = self._context_text(minimum["dimensions"])
            sentences.append(
                f"{metric}最高为{self._display(maximum['value'])}"
                f"{f'（{max_context}）' if max_context else ''}；"
                f"最低为{self._display(minimum['value'])}"
                f"{f'（{min_context}）' if min_context else ''}。"
            )
        return "".join(sentences)

    @staticmethod
    def _number(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _is_numeric_column(self, rows: list[dict[str, Any]], column: str) -> bool:
        values = [row.get(column) for row in rows if row.get(column) is not None]
        return bool(values) and all(self._number(value) is not None for value in values)

    def _dimension_variants(self, rows: list[dict[str, Any]], dimensions: list[str]) -> set[str]:
        variants: set[str] = set()
        for row in rows:
            for dimension in dimensions:
                variants.update(self._variants(row.get(dimension)))
        return variants

    @staticmethod
    def _variants(value: Any) -> set[str]:
        if value is None:
            return set()
        text = value.isoformat() if isinstance(value, (date, datetime)) else str(value)
        variants = {text}
        match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
        if match:
            year, month, day = (int(item) for item in match.groups())
            variants.update({f"{year}年{month}月{day}日", f"{month}月{day}日", f"{month:02d}月{day:02d}日"})
        month_match = re.fullmatch(r"(\d{4})-(\d{2})", text)
        if month_match:
            variants.add(f"{int(month_match.group(1))}年{int(month_match.group(2))}月")
        return variants

    @staticmethod
    def _display(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:,.2f}".rstrip("0").rstrip(".")
        return str(value)

    @staticmethod
    def _context_text(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        return "、".join(str(value) for value in rows[0].values() if value is not None)
