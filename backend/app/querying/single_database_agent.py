from __future__ import annotations

import json
import re
from fnmatch import fnmatch
from typing import Any, Callable

import sqlglot
from sqlglot import exp

from ..errors import PipelineStageError
from ..mcp_runtime.client import LocalMcpClient
from ..model_client import ModelClient
from ..skills import SkillDefinition
from .sql_continuity import SqlContinuityGuard


class SingleDatabaseAgent:
    """让模型通过MCP工具完成单数据库查询。"""

    def __init__(
        self,
        model_client: ModelClient,
        mcp_client_factory: Callable[[dict[str, Any]], LocalMcpClient],
        skill: SkillDefinition,
        max_tool_calls: int = 3,
    ) -> None:
        self.model_client = model_client
        self.mcp_client_factory = mcp_client_factory
        self.skill = skill
        self.max_tool_calls = min(max_tool_calls, skill.max_tool_calls)

    def prepare(
        self,
        query: str,
        database: str,
        schema_graph: dict[str, Any],
        schema_context: str,
        retrieval: dict[str, Any],
        workspace: dict[str, Any],
        access_scope: dict[str, Any],
        previous_sql: str = "",
        follow_up_query: str = "",
    ) -> dict[str, Any]:
        database_tool = f"query_{database}"
        mcp_client = self.mcp_client_factory(access_scope)

        # 每次请求都通过MCP tools/list获取当前工具定义。
        catalog = mcp_client.list_tools()
        tools = [
            tool
            for tool in catalog
            if any(fnmatch(tool["name"], pattern) for pattern in self.skill.allowed_tools)
            and (not tool["name"].startswith("query_") or tool["name"] == database_tool)
        ]
        # 明确年月已经给出时，不向模型暴露时间解析工具，避免三次调用额度被无意义消耗。
        if not self._requires_time_resolution(query):
            tools = [
                tool for tool in tools
                if tool["name"] not in {"current_datetime", "resolve_date_range"}
            ]
        tool_names = {tool["name"] for tool in tools}
        if database_tool not in tool_names:
            raise PipelineStageError(
                "mcp_tool_discovery",
                f"没有找到数据库工具：{database_tool}",
            )

        deterministic_sql = SqlContinuityGuard.clear_filter_sql(
            previous_sql, follow_up_query
        )
        if deterministic_sql:
            tool_result = mcp_client.call_tool(
                database_tool, {"sql": deterministic_sql}
            )
            trace = {
                "call_index": 1,
                "tool": database_tool,
                "arguments": {"sql": deterministic_sql},
                "result": tool_result,
                "reason": "明确取消地区筛选，基于上一轮已验证SQL确定性修改",
                "validation": "deterministic_filter_clear",
            }
            return {
                "action": "executed",
                "execution": tool_result,
                "tool_trace": [trace],
                "source": "deterministic_follow_up",
            }

        system = (
            f"你是单数据库问数智能体。\n\n{self.skill.instructions}\n\n"
            "生成 SQL 时还必须遵守以下面向产品展示的契约：\n"
            "1. 严格服从用户要求的结果粒度。时间字段仅用于筛选时，不得擅自加入 "
            "SELECT 或 GROUP BY；只有用户明确要求按天、按月等时间粒度展示时才按时间分组。\n"
            "2. 面向业务用户输出维度时优先返回名称、标题等可读字段。汇总查询中的ID/编号默认只用于JOIN；"
            "找出、列出、筛选、清单等明细任务若result_contract给出required_identifiers，必须同时返回这些记录标识，"
            "以便回查和导出交付；若给出required_detail_fields，必须全部返回，增加记录标识不能替代或删除名称等业务字段。"
            "如果用户要求按店铺、商品、渠道等维度展示且Schema中存在对应名称，必须关联并返回名称。\n"
            "3. 比例、率、占比、完成率在 SQL 中统一返回 0 到 1 的小数，不乘以 100，"
            "因为前端会统一格式化为百分比；字段别名中不要添加 '(%)'。\n"
            "4. 用户要求找出、筛选某类对象时，筛选条件必须落实到 WHERE、HAVING 或 QUALIFY；"
            "不能只用 CASE 标记后仍返回全部对象。\n"
            "5. Schema 中已经存在唯一匹配字段时必须直接使用，不得反问用户字段名。\n"
            "6. JOIN 的左右表和关联字段必须严格使用 schema_graph.joins 中声明的关系，"
            "不能因为两个表存在同名字段就自行关联；如果关系已在 schema_graph.joins 中声明，"
            "必须直接使用，不得询问用户是否允许。\n"
            "如果已完成的数据库工具调用失败，必须根据 error 和输入的 "
            "Schema 修正 SQL，不得重复提交相同的失败 SQL。"
        )

        observations: list[dict[str, Any]] = []
        tool_trace: list[dict[str, Any]] = []
        base_payload = {
            "query": query,
            "database": database,
            "result_contract": self._result_contract(query, schema_graph),
            "schema_graph": schema_graph,
            "retrieval": {
                "threshold": retrieval.get("threshold"),
                "selected_fields": retrieval.get("hits", []),
                "low_confidence_candidates": retrieval.get("low_confidence_candidates", []),
            },
            "confirmed_fields": workspace.get("schema_fields", []),
            "confirmed_parameters": workspace.get("confirmed_parameters", {}),
            "schema_text": schema_context,
            "mcp_tools": tools,
        }
        continuity_mode = SqlContinuityGuard.classify(follow_up_query) if previous_sql else None
        if continuity_mode:
            base_payload["query_continuity"] = {
                "mode": continuity_mode,
                "allowed_change": SqlContinuityGuard.mode_label(continuity_mode),
                "previous_sql": previous_sql,
                "instruction": "只修改用户本轮明确要求的口径，其余表、指标、维度和时间必须继承。",
            }

        last_database_result: dict[str, Any] | None = None
        try:
            for call_index in range(1, self.max_tool_calls + 1):
                payload = {**base_payload, "tool_results": observations}
                decision = self.model_client.chat_json(
                    system,
                    json.dumps(payload, ensure_ascii=False),
                )
                decision = self._normalize_decision(decision, database_tool)

                action = str(decision.get("action") or "")
                if action not in self.skill.output_actions:
                    protocol_error = {
                        "success": False,
                        "error": (
                            f"动作协议错误：必须返回 action={'|'.join(self.skill.output_actions)}，"
                            f"实际为 {action or '缺失'}"
                        ),
                    }
                    tool_trace.append({
                        "call_index": call_index,
                        "tool": "decision_contract",
                        "arguments": decision,
                        "result": protocol_error,
                        "validation": "decision_contract",
                    })
                    observations.append({
                        "tool": "decision_contract",
                        "result": protocol_error,
                        "instruction": (
                            "上一响应虽是JSON，但不符合动作协议。请严格返回call_tool或clarify结构；"
                            "信息充分时应直接调用数据库工具。"
                        ),
                    })
                    continue

                if action == "clarify":
                    clarification = decision.get("clarification")
                    if not isinstance(clarification, dict) or len(
                        clarification.get("options") or []
                    ) < 2:
                        raise ValueError("智能体返回的澄清信息不完整")
                    resolved_field = self._resolve_redundant_field_clarification(
                        clarification, schema_graph
                    )
                    if resolved_field:
                        guard_result = {
                            "success": True,
                            "resolved_field": resolved_field,
                            "reason": "Schema中存在唯一匹配字段，无需向用户澄清",
                        }
                        tool_trace.append({
                            "call_index": call_index,
                            "tool": "clarification_guard",
                            "arguments": clarification,
                            "result": guard_result,
                            "reason": str(decision.get("reason") or ""),
                        })
                        observations.append({
                            "tool": "clarification_guard",
                            "result": guard_result,
                            "instruction": (
                                f"字段 {resolved_field} 已由Schema唯一确认，请直接生成并执行SQL，"
                                "不要再次澄清字段名。"
                            ),
                        })
                        continue
                    resolved_join = self._resolve_redundant_join_clarification(
                        clarification, schema_graph
                    )
                    if resolved_join:
                        guard_result = {
                            "success": True,
                            "resolved_join": resolved_join,
                            "reason": "该关联已由Schema声明，无需用户授权",
                        }
                        tool_trace.append({
                            "call_index": call_index,
                            "tool": "clarification_guard",
                            "arguments": clarification,
                            "result": guard_result,
                            "reason": str(decision.get("reason") or ""),
                        })
                        observations.append({
                            "tool": "clarification_guard",
                            "result": guard_result,
                            "instruction": (
                                f"关联 {resolved_join} 已由Schema确认，请直接生成并执行SQL，"
                                "不要再次询问用户是否允许。"
                            ),
                        })
                        continue
                    return {
                        "action": "clarify",
                        "clarification": clarification,
                        "tool_trace": tool_trace,
                    }

                if action != "call_tool":
                    raise ValueError("智能体必须返回call_tool或clarify")

                tool_name = str(decision.get("tool_name") or "")
                arguments = decision.get("arguments")
                if tool_name not in tool_names:
                    raise ValueError(f"智能体选择了未提供的MCP工具：{tool_name}")
                if not isinstance(arguments, dict):
                    raise ValueError("MCP工具参数必须是JSON对象")

                if tool_name == database_tool:
                    candidate_sql = str(arguments.get("sql") or "")
                    contract_error = self._sql_contract_error(
                        candidate_sql, query, schema_graph
                    )
                    continuity_error = SqlContinuityGuard.validate(
                        previous_sql, candidate_sql, continuity_mode
                    )
                    contract_error = contract_error or continuity_error
                    if contract_error:
                        tool_result = {
                            "success": False,
                            "sql": candidate_sql,
                            "columns": [],
                            "rows": [],
                            "error": contract_error,
                        }
                        tool_trace.append({
                            "call_index": call_index,
                            "tool": tool_name,
                            "arguments": arguments,
                            "result": tool_result,
                            "reason": str(decision.get("reason") or ""),
                            "validation": (
                                "sql_continuity_guard"
                                if continuity_error else "sql_product_contract"
                            ),
                        })
                        last_database_result = tool_result
                        observations.append({
                            "tool": tool_name,
                            "result": tool_result,
                            "instruction": (
                                "SQL改变了用户未要求修改的上一轮口径，请基于previous_sql只修改"
                                f"{SqlContinuityGuard.mode_label(continuity_mode or '')}后重写。"
                                if continuity_error else
                                "SQL违反产品输出契约，请根据错误原因和Schema重写。"
                            ),
                        })
                        continue

                tool_result = mcp_client.call_tool(tool_name, arguments)
                trace = {
                    "call_index": call_index,
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": tool_result,
                    "reason": str(decision.get("reason") or ""),
                }
                tool_trace.append(trace)

                if tool_name == database_tool:
                    if tool_result.get("success"):
                        database_attempts = sum(
                            1 for item in tool_trace if item.get("tool") == database_tool
                        )
                        return {
                            "action": "executed",
                            "execution": tool_result,
                            "tool_trace": tool_trace,
                            "source": (
                                "model_mcp_repaired"
                                if database_attempts > 1
                                else "model_mcp"
                            ),
                        }

                    # 把 DuckDB 的精确错误作为观察结果回传，供模型修正 SQL。
                    last_database_result = tool_result
                    observations.append({
                        "tool": tool_name,
                        "result": tool_result,
                        "instruction": (
                            "上一条 SQL 执行失败。请根据 error 和 schema_text "
                            "修正 SQL，不要重复相同 SQL。"
                        ),
                    })
                    continue

                observations.append({"tool": tool_name, "result": tool_result})

            if last_database_result is not None:
                return {
                    "action": "executed",
                    "execution": last_database_result,
                    "tool_trace": tool_trace,
                    "source": "model_mcp_retry_exhausted",
                }
            raise ValueError(f"MCP工具调用超过上限：{self.max_tool_calls}")
        except PipelineStageError:
            raise
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            raise PipelineStageError("single_database_agent", str(exc)) from exc

    @staticmethod
    def _requires_time_resolution(query: str) -> bool:
        has_explicit_date = bool(
            re.search(r"20\d{2}\s*年\s*\d{1,2}\s*月", query)
            or re.search(r"20\d{2}[-/]\d{1,2}", query)
        )
        if has_explicit_date:
            return False
        return any(
            term in query
            for term in ("今天", "昨天", "本周", "上周", "本月", "上月", "今年", "去年", "最近")
        )

    @staticmethod
    def _normalize_decision(
        decision: dict[str, Any], database_tool: str
    ) -> dict[str, Any]:
        if decision.get("action"):
            return decision
        if isinstance(decision.get("sql"), str) and decision["sql"].strip():
            return {
                "action": "call_tool",
                "tool_name": database_tool,
                "arguments": {"sql": decision["sql"]},
                "reason": str(decision.get("reason") or "模型直接返回SQL，已规范化为工具调用"),
            }
        if decision.get("tool_name") and isinstance(decision.get("arguments"), dict):
            return {**decision, "action": "call_tool"}
        return decision

    @staticmethod
    def _resolve_redundant_field_clarification(
        clarification: dict[str, Any], schema_graph: dict[str, Any]
    ) -> str | None:
        prompt = " ".join(
            str(clarification.get(key) or "")
            for key in ("parameter", "question", "reason")
        ).lower()
        if "字段" not in prompt and "field" not in prompt:
            return None

        available = {
            str(field.get(key) or "").strip().lower()
            for field in schema_graph.get("fields", [])
            for key in ("name", "sql_name")
            if field.get(key)
        }
        matched: list[str] = []
        for option in clarification.get("options") or []:
            if not isinstance(option, dict):
                continue
            candidates = {
                str(option.get(key) or "").strip().lower()
                for key in ("id", "label")
                if option.get(key)
            }
            matches = candidates & available
            if matches:
                matched.extend(sorted(matches))
        unique_matches = list(dict.fromkeys(matched))
        return unique_matches[0] if len(unique_matches) == 1 else None

    @staticmethod
    def _resolve_redundant_join_clarification(
        clarification: dict[str, Any], schema_graph: dict[str, Any]
    ) -> str | None:
        prompt = " ".join(
            str(clarification.get(key) or "")
            for key in ("parameter", "question", "reason")
        )
        proposed = re.search(
            r"([A-Za-z_][\w.]*)\.([A-Za-z_]\w*)\s*=\s*"
            r"([A-Za-z_][\w.]*)\.([A-Za-z_]\w*)",
            prompt,
        )
        if not proposed:
            return None

        def table_name(value: Any) -> str:
            return str(value or "").strip().strip("`\"").lower().rsplit(".", 1)[-1]

        left_table, left_field, right_table, right_field = proposed.groups()
        candidate = (
            table_name(left_table), left_field.lower(),
            table_name(right_table), right_field.lower(),
        )
        allowed: set[tuple[str, str, str, str]] = set()
        for join in schema_graph.get("joins", []):
            relation = (
                table_name(join.get("left_table_name") or join.get("left_table")),
                str(join.get("left_field") or "").lower(),
                table_name(join.get("right_table_name") or join.get("right_table")),
                str(join.get("right_field") or "").lower(),
            )
            allowed.add(relation)
            allowed.add((relation[2], relation[3], relation[0], relation[1]))
        if candidate not in allowed:
            return None
        return (
            f"{candidate[0]}.{candidate[1]} = "
            f"{candidate[2]}.{candidate[3]}"
        )

    @staticmethod
    def _sql_contract_error(
        sql: str, query: str, schema_graph: dict[str, Any]
    ) -> str | None:
        try:
            statement = sqlglot.parse_one(sql, read="duckdb")
        except Exception:
            return None  # 语法错误仍交给 DuckDB，保留更精确的错误信息。

        asks_time_grain = any(
            term in query for term in ("每天", "每日", "按天", "逐日", "各日", "每月", "按月", "逐月")
        )
        if not asks_time_grain:
            for group in statement.find_all(exp.Group):
                grouped_names = {
                    column.name.lower() for column in group.find_all(exp.Column)
                }
                if any(
                    name.endswith(("_date", "_at")) or name in {"date", "日期", "月份"}
                    for name in grouped_names
                ):
                    return "结果粒度错误：用户未要求按天或按月展示，时间字段只能用于筛选，不能加入GROUP BY"

        asks_below_target = any(
            term in query
            for term in ("未完成", "未达标", "低于目标", "没有完成", "没完成")
        )
        if asks_below_target:
            filtering_nodes = [
                *statement.find_all(exp.Where),
                *statement.find_all(exp.Having),
                *statement.find_all(exp.Qualify),
            ]
            has_target_filter = any(
                isinstance(comparison, (exp.LT, exp.LTE))
                and any(
                    marker in comparison.sql(dialect="duckdb").lower()
                    for marker in ("target", "目标")
                )
                for node in filtering_nodes
                for comparison in node.walk()
            )
            if not has_target_filter:
                return (
                    "筛选条件缺失：用户要求只找出未完成目标的对象，必须在WHERE、HAVING或QUALIFY中"
                    "使用实际值 < 目标值进行筛选，不能只用CASE标记后返回全部对象"
                )

        def normalize_table(value: Any) -> str:
            return str(value or "").strip().strip('"`').lower().rsplit(".", 1)[-1]

        aliases: dict[str, str] = {}
        for table in statement.find_all(exp.Table):
            table_name = normalize_table(table.name)
            aliases[table_name] = table_name
            if table.alias:
                aliases[table.alias.lower()] = table_name
        known_tables = {
            normalize_table(table.get(key))
            for table in schema_graph.get("tables", [])
            for key in ("id", "name")
            if table.get(key)
        }
        physical_tables = {
            normalize_table(table.name) for table in statement.find_all(exp.Table)
        }
        contract = SingleDatabaseAgent._result_contract(query, schema_graph)
        required_tables = set(contract.get("required_tables", []))
        missing_tables = required_tables - physical_tables
        if missing_tables:
            return (
                "统计总体错误：该业务口径必须基于主数据表 "
                f"{', '.join(sorted(required_tables))} 计算，当前缺少 "
                f"{', '.join(sorted(missing_tables))}"
            )
        forbidden_tables = set(contract.get("forbidden_tables", []))
        unexpected_tables = forbidden_tables & physical_tables
        if unexpected_tables:
            return (
                "统计总体错误：该问题询问SKU主数据的定价水平，不能混入订单表或订单明细表；"
                f"请移除 {', '.join(sorted(unexpected_tables))}"
            )
        if contract.get("cover_address_must_be_empty"):
            normalized_sql = statement.sql(dialect="duckdb").lower()
            if "public_third_part.jpeg" in normalized_sql:
                return (
                    "筛选语义错误：默认封面仍然是有效的封面地址；"
                    "“没有封面地址”不能包含使用public_third_part.jpeg的记录"
                )
            has_null_and_blank = (
                bool(re.search(r"(?:\w+\.)?image_path\s+is\s+null", normalized_sql))
                and bool(
                    re.search(
                        r"(?:trim\s*\([^)]*image_path[^)]*\)|(?:\w+\.)?image_path)\s*=\s*''",
                        normalized_sql,
                    )
                )
            )
            has_coalesced_blank = bool(
                re.search(
                    r"coalesce\s*\([^)]*image_path[^)]*,\s*''\s*\)\s*=\s*''",
                    normalized_sql,
                )
            )
            if not (has_null_and_blank or has_coalesced_blank):
                return (
                    "筛选条件缺失：“没有封面地址”必须同时覆盖image_path为NULL和空字符串，"
                    "不能把默认封面当作空地址"
                )
        allowed_joins: set[tuple[str, str, str, str]] = set()
        for join in schema_graph.get("joins", []):
            left_table = normalize_table(join.get("left_table_name") or join.get("left_table"))
            right_table = normalize_table(join.get("right_table_name") or join.get("right_table"))
            left_field = str(join.get("left_field") or "").lower()
            right_field = str(join.get("right_field") or "").lower()
            allowed_joins.add((left_table, left_field, right_table, right_field))
            allowed_joins.add((right_table, right_field, left_table, left_field))
        for join in statement.find_all(exp.Join):
            condition = join.args.get("on")
            if condition is None:
                continue
            joined_table = None
            if isinstance(join.this, exp.Table):
                joined_table = normalize_table(join.this.name)
            validates_join_target = False
            joins_unknown_source = False
            for equality in condition.find_all(exp.EQ):
                if not isinstance(equality.this, exp.Column) or not isinstance(equality.expression, exp.Column):
                    continue
                left = equality.this
                right = equality.expression
                left_table = aliases.get(left.table.lower()) if left.table else None
                right_table = aliases.get(right.table.lower()) if right.table else None
                if joined_table and joined_table in {left_table, right_table}:
                    other_table = right_table if left_table == joined_table else left_table
                    if other_table is None or other_table not in known_tables:
                        # CTE/派生表不属于物理Schema关系，由其内部查询负责约束。
                        joins_unknown_source = True
                if (
                    not left_table
                    or not right_table
                    or left_table == right_table
                    or left_table not in known_tables
                    or right_table not in known_tables
                ):
                    continue
                relationship = (
                    left_table, left.name.lower(), right_table, right.name.lower()
                )
                if allowed_joins and relationship not in allowed_joins:
                    return (
                        "关联关系错误：JOIN必须使用Schema声明的关联字段；"
                        f"不允许 {left.sql()} = {right.sql()}"
                    )
                if joined_table in {left_table, right_table}:
                    validates_join_target = True
            if (
                joined_table in known_tables
                and not validates_join_target
                and not joins_unknown_source
            ):
                return (
                    "关联关系错误：JOIN的ON条件必须使用Schema声明的字段等值关系，"
                    f"并同时关联新加入的表 {joined_table} 与已有数据表"
                )

        outer_select = statement.find(exp.Select)
        if outer_select:
            if asks_below_target:
                projected_sql = " ".join(
                    projection.sql(dialect="duckdb").lower()
                    for projection in outer_select.expressions
                )
                if not any(marker in projected_sql for marker in ("target", "目标")):
                    return (
                        "展示字段缺失：筛选未完成目标的对象时，结果必须同时展示实际值和目标值，"
                        "便于用户核对判定依据"
                    )
            for projection in outer_select.expressions:
                alias = projection.alias_or_name or ""
                expression_sql = projection.this.sql(dialect="duckdb") if isinstance(projection, exp.Alias) else projection.sql(dialect="duckdb")
                if ("率" in alias or "占比" in alias or "%" in alias) and re.search(
                    r"\*\s*100(?:\.0+)?\b", expression_sql
                ):
                    return "比例单位错误：比例字段必须返回0到1的小数，不能乘以100，前端会负责百分比格式化"

            selected_names = {
                column.name.lower()
                for projection in outer_select.expressions
                for column in projection.find_all(exp.Column)
            }
            required_identifiers = SingleDatabaseAgent._result_contract(
                query, schema_graph
            ).get("required_identifiers", [])
            missing_identifiers = [
                field for field in required_identifiers if field.lower() not in selected_names
            ]
            if missing_identifiers:
                return (
                    "交付字段缺失：明细查询必须返回记录唯一标识 "
                    f"{', '.join(missing_identifiers)}，便于页面回查和Excel交付"
                )
            required_detail_fields = SingleDatabaseAgent._result_contract(
                query, schema_graph
            ).get("required_detail_fields", [])
            missing_detail_fields = [
                field for field in required_detail_fields if field.lower() not in selected_names
            ]
            if missing_detail_fields:
                return (
                    "业务字段缺失：明细查询除记录标识外还必须返回默认业务核对字段 "
                    f"{', '.join(missing_detail_fields)}；增加主键不能删除名称等可读字段"
                )
            available_names = {
                str(field.get("name") or "").lower()
                for field in schema_graph.get("fields", [])
            }
            readable_dimensions = (
                ("店铺", "store_id", "store_name"),
                ("商品", "product_id", "product_name"),
                ("渠道", "channel_id", "channel_name"),
            )
            for label, identifier, readable_name in readable_dimensions:
                if (
                    label in query
                    and identifier in selected_names
                    and readable_name in available_names
                    and readable_name not in selected_names
                ):
                    return f"展示字段错误：查询结果应返回{label}名称 {readable_name}，{identifier} 仅用于关联"
        return None

    @staticmethod
    def _result_contract(query: str, schema_graph: dict[str, Any]) -> dict[str, Any]:
        dimensions: list[str] = []
        readable_dimensions = (
            ("店铺", "store_name"),
            ("商品", "product_name"),
            ("渠道", "channel_name"),
            ("地区", "region"),
            ("订单状态", "order_status"),
        )
        available = {
            str(field.get("name") or "") for field in schema_graph.get("fields", [])
        }
        for label, field_name in readable_dimensions:
            if label in query and field_name in available:
                dimensions.append(field_name)
        time_grain = next(
            (
                grain
                for terms, grain in (
                    (("每天", "每日", "按天", "逐日", "各日"), "day"),
                    (("每月", "按月", "逐月"), "month"),
                )
                if any(term in query for term in terms)
            ),
            "filter_only",
        )
        detail_terms = ("找出", "列出", "清单", "明细", "哪些", "筛选")
        summary_terms = ("统计", "汇总", "数量", "多少", "占比", "平均", "合计")
        is_detail = any(term in query for term in detail_terms) and not any(
            term in query for term in summary_terms
        )
        required_identifiers: list[str] = []
        required_detail_fields: list[str] = []
        tables = schema_graph.get("tables", [])
        if is_detail and len(tables) == 1:
            required_identifiers = [
                str(field_name)
                for field_name in tables[0].get("primary_key", [])
                if field_name
            ]
            required_detail_fields = [
                str(field_name)
                for field_name in tables[0].get("default_detail_fields", [])
                if field_name
            ]
        sku_master_price = (
            bool(re.search(r"SKU", query, re.IGNORECASE))
            and any(term in query for term in ("销售价", "标价", "定价"))
            and any(term in query for term in ("平均", "均值", "均价"))
            and any(term in query for term in ("店铺", "大区", "地区", "区域"))
        )
        missing_cover_address = bool(
            re.search(
                r"(?:没有|无)(?:封面地址|封面URL|封面路径)|"
                r"(?:封面地址|封面URL|封面路径)(?:为空|是空的)",
                query,
                re.IGNORECASE,
            )
        )
        return {
            "required_group_dimensions": dimensions,
            "time_grain": time_grain,
            "time_rule": (
                "时间字段只能出现在WHERE，不能出现在SELECT或GROUP BY"
                if time_grain == "filter_only"
                else f"按{time_grain}粒度分组"
            ),
            "rate_representation": "0_to_1_decimal",
            "display_rule": "汇总查询名称优先；明细查询同时返回可读名称和记录唯一标识",
            "required_identifiers": required_identifiers,
            "required_detail_fields": required_detail_fields,
            "required_tables": (
                ["product_skus", "products", "stores"] if sku_master_price else []
            ),
            "forbidden_tables": (
                ["orders", "order_items"] if sku_master_price else []
            ),
            "cover_address_must_be_empty": missing_cover_address,
            "allowed_joins": [
                {
                    "left_table": join.get("left_table_name") or join.get("left_table"),
                    "left_field": join.get("left_field"),
                    "right_table": join.get("right_table_name") or join.get("right_table"),
                    "right_field": join.get("right_field"),
                }
                for join in schema_graph.get("joins", [])
            ],
            "required_filter": (
                "image_path必须为NULL或空字符串，且不能包含默认封面值"
                if missing_cover_address
                else
                "仅返回实际值低于目标值的对象；必须使用WHERE、HAVING或QUALIFY筛选，不能只用CASE标记"
                if any(
                    term in query
                    for term in ("未完成", "未达标", "低于目标", "没有完成", "没完成")
                )
                else None
            ),
            "required_evidence_columns": (
                ["actual_value", "target_value"]
                if any(
                    term in query
                    for term in ("未完成", "未达标", "低于目标", "没有完成", "没完成")
                )
                else []
            ),
        }
