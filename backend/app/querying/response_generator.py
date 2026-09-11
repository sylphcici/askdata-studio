from __future__ import annotations

import json
from typing import Any

from ..config import Settings, settings
from ..model_client import ModelClient
from .models import SqlExecution
from .summary_fidelity import SummaryFidelityChecker


class ResponseGenerator:
    """生成问答内容和查询结果说明。"""

    def __init__(
        self,
        model_client: ModelClient,
        config: Settings | None = None,
    ) -> None:
        self.model_client = model_client
        self.table_row_limit = max(1, (config or settings).context_table_row_limit)
        self.fidelity_checker = SummaryFidelityChecker()

    def finalize(
        self,
        query: str,
        execution: SqlExecution,
        schema_context: str,
        analysis_context: str,
    ) -> dict[str, Any]:
        verified_facts = self.fidelity_checker.build_facts(execution.rows)
        system = """你是查询结果整理器。检查结果能否回答问题，并生成简短标题和一到两句说明。
只能使用结果数据和“程序已验证事实”中存在的信息。最高、最低、最多、最少等结论必须严格服从程序已验证事实；不得自行补充因果解释。只返回JSON：
{"valid":true,"reason":"...","title":"...","analysis":"..."}。"""
        user = (
            f"问题：{query}\nSQL：{execution.sql}\n列：{execution.columns}\n"
            f"结果数据：{execution.rows[: self.table_row_limit]}\nSchema：{schema_context}\n"
            f"程序已验证事实：{json.dumps(verified_facts, ensure_ascii=False)}\n"
            f"用户保存的分析表格：{analysis_context or '无'}"
        )
        try:
            payload = self.model_client.chat_json(system, user)
            analysis = str(payload.get("analysis") or f"查询返回{len(execution.rows)}行。")
            fidelity = self.fidelity_checker.check(analysis, execution.rows)
            guard_used = not fidelity.valid
            if guard_used:
                analysis = self.fidelity_checker.fallback_summary(fidelity.facts)
            return {
                "valid": bool(payload.get("valid", True)),
                "reason": str(payload.get("reason") or "结果检查通过"),
                "title": str(payload.get("title") or "查询结果"),
                "analysis": analysis,
                "summary_faithful": fidelity.valid,
                "summary_guard_used": guard_used,
                "summary_fidelity_issues": fidelity.issues,
                "verified_facts": fidelity.facts,
            }
        except RuntimeError as exc:
            return {
                "valid": True,
                "reason": "结果说明模型不可用，已使用程序验证事实生成说明",
                "title": "查询结果",
                "analysis": self.fidelity_checker.fallback_summary(verified_facts),
                "summary_faithful": False,
                "summary_guard_used": True,
                "summary_fidelity_issues": [f"结果说明生成失败：{exc}"],
                "verified_facts": verified_facts,
            }
