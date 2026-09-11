from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp


@dataclass(frozen=True)
class SqlSignature:
    tables: frozenset[str]
    metrics: frozenset[tuple[str, tuple[str, ...]]]
    groups: frozenset[str]
    dates: tuple[str, ...]
    time_fields: frozenset[tuple[str, str]]
    filters: frozenset[tuple[str, str, tuple[str, ...]]]


class SqlContinuityGuard:
    """约束多轮追问只改变用户明确要求修改的查询口径。"""

    @staticmethod
    def classify(query: str) -> str | None:
        compact = re.sub(r"\s+", "", query)
        if any(term in compact for term in ("按店铺", "按商品", "按渠道", "按天", "按月", "拆分", "下钻")):
            return "dimension_change"
        if any(term in compact for term in ("换成订单", "改成订单", "换成GMV", "改成GMV", "换成销售额", "改成销售额")):
            return "metric_change"
        if re.search(r"(?:换成|改成|改为|看|查询).{0,8}(?:年|月|日|周|季度)", compact):
            return "time_change"
        if any(term in compact for term in ("只看", "仅看", "限定", "筛选", "排除", "不限制", "不限")):
            return "filter_change"
        return None

    @classmethod
    def validate(cls, previous_sql: str, current_sql: str, mode: str | None) -> str | None:
        if not previous_sql or not current_sql or not mode:
            return None
        try:
            before = cls.signature(previous_sql)
            after = cls.signature(current_sql)
        except Exception:
            return None

        protected: list[tuple[str, object, object]] = []
        if mode in {"filter_change", "time_change", "metric_change"}:
            protected.append(("分组维度", before.groups, after.groups))
        if mode in {"filter_change", "time_change"}:
            protected.append(("指标及聚合方式", before.metrics, after.metrics))
        if mode in {"filter_change", "metric_change"}:
            protected.append(("时间范围", before.dates, after.dates))
        if mode in {"filter_change", "time_change", "dimension_change", "metric_change"}:
            protected.append(("时间字段", before.time_fields, after.time_fields))
        if mode in {"filter_change", "time_change", "metric_change"}:
            protected.append(("数据表", before.tables, after.tables))
        if mode == "dimension_change":
            protected.extend([
                ("指标及聚合方式", before.metrics, after.metrics),
                ("时间范围", before.dates, after.dates),
            ])

        changed = [label for label, old, new in protected if old != new]
        if mode in {"time_change", "dimension_change", "metric_change"} and not before.filters.issubset(after.filters):
            changed.append("既有筛选条件")
        if not changed:
            return None
        return (
            "多轮查询口径漂移：本轮只允许修改"
            f"{cls.mode_label(mode)}，但SQL还改变了{'、'.join(changed)}。"
            "请保留上一轮未被用户修改的口径后重写SQL。"
        )

    @staticmethod
    def mode_label(mode: str) -> str:
        return {
            "filter_change": "筛选条件",
            "time_change": "时间范围",
            "dimension_change": "分组维度",
            "metric_change": "查询指标",
        }.get(mode, "用户指定内容")

    @staticmethod
    def clear_filter_sql(previous_sql: str, query: str) -> str | None:
        """对明确的取消地区限制，直接删除上一轮SQL中的地区谓词。"""
        compact = re.sub(r"\s+", "", query)
        if not any(term in compact for term in ("不限制地区", "不限地区", "取消地区限制")):
            return None
        try:
            statement = sqlglot.parse_one(previous_sql, read="duckdb")
        except Exception:
            return None
        where = statement.args.get("where")
        if not isinstance(where, exp.Where):
            return None

        def remove_region(node: exp.Expression) -> exp.Expression | None:
            if isinstance(node, exp.And):
                left = remove_region(node.this)
                right = remove_region(node.expression)
                if left is None:
                    return right
                if right is None:
                    return left
                return exp.and_(left, right)
            if any(column.name.lower() == "region" for column in node.find_all(exp.Column)):
                return None
            return node.copy()

        remaining = remove_region(where.this)
        if remaining is None:
            statement.set("where", None)
        else:
            where.set("this", remaining)
        rewritten = statement.sql(dialect="duckdb")
        return rewritten if rewritten != previous_sql.strip().rstrip(";") else None

    @staticmethod
    def signature(sql: str) -> SqlSignature:
        statement = sqlglot.parse_one(sql, read="duckdb")
        table_nodes = list(statement.find_all(exp.Table))
        tables = frozenset(table.name.lower() for table in table_nodes)
        aliases: dict[str, str] = {}
        for table in table_nodes:
            name = table.name.lower()
            aliases[name] = name
            if table.alias:
                aliases[table.alias.lower()] = name

        def column_key(column: exp.Column) -> tuple[str, str]:
            qualifier = str(column.table or "").lower()
            if qualifier:
                table_name = aliases.get(qualifier, qualifier)
            else:
                table_name = next(iter(tables)) if len(tables) == 1 else ""
            return table_name, column.name.lower()

        metrics: set[tuple[str, tuple[str, ...]]] = set()
        for node in statement.walk():
            if isinstance(node, (exp.Sum, exp.Avg, exp.Count, exp.Max, exp.Min)):
                columns = tuple(sorted(column.name.lower() for column in node.find_all(exp.Column)))
                metrics.add((node.key.lower(), columns))
        groups = frozenset(
            column.name.lower()
            for group in statement.find_all(exp.Group)
            for column in group.find_all(exp.Column)
        )
        dates = tuple(sorted({
            str(literal.this)
            for literal in statement.find_all(exp.Literal)
            if literal.is_string and re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", str(literal.this))
        }))
        filter_values: dict[tuple[str, str], set[str]] = {}
        time_fields: set[tuple[str, str]] = set()
        for clause in [*statement.find_all(exp.Where), *statement.find_all(exp.Having)]:
            for predicate in clause.walk():
                if isinstance(predicate, (exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Between)):
                    predicate_dates = [
                        str(item.this)
                        for item in predicate.find_all(exp.Literal)
                        if item.is_string
                        and re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", str(item.this))
                    ]
                    if predicate_dates:
                        time_fields.update(
                            column_key(item) for item in predicate.find_all(exp.Column)
                        )
                column: exp.Column | None = None
                literals: list[exp.Literal] = []
                if isinstance(predicate, exp.In) and isinstance(predicate.this, exp.Column):
                    column = predicate.this
                    literals = [item for item in predicate.expressions if isinstance(item, exp.Literal)]
                elif isinstance(predicate, exp.EQ):
                    if isinstance(predicate.this, exp.Column) and isinstance(predicate.expression, exp.Literal):
                        column, literals = predicate.this, [predicate.expression]
                    elif isinstance(predicate.expression, exp.Column) and isinstance(predicate.this, exp.Literal):
                        column, literals = predicate.expression, [predicate.this]
                values = tuple(sorted(str(item.this) for item in literals))
                if not column or not values or all(re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", value) for value in values):
                    continue
                table_name, field_name = column_key(column)
                filter_values.setdefault((table_name, field_name), set()).update(values)
        filters = frozenset(
            (table_name, field_name, tuple(sorted(values)))
            for (table_name, field_name), values in filter_values.items()
        )
        return SqlSignature(
            tables,
            frozenset(metrics),
            groups,
            dates,
            frozenset(time_fields),
            filters,
        )
