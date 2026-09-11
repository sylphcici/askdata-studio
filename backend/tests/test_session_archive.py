from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.config import Settings
from app.models import Clarification, ClarificationOption, Interpretation, QueryResult
from app.services.session_archive import SessionArchive
from app.services.session_context import SessionContext


class NoopModel:
    def chat(self, system: str, user: str) -> str:
        return "摘要"


class SessionArchiveTest(unittest.TestCase):
    def test_ui_conversations_persist_and_are_isolated_by_user(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = SessionArchive(Path(temp_dir) / "sessions.db")
            base = {
                "id": "conversation-1",
                "title": "地区销售",
                "updatedAt": 1000,
                "turns": [{"query": "查看地区销售", "result": {"status": "completed"}}],
                "workspace": {"schema_fields": []},
            }
            archive.save_conversation("sales-user", base)
            archive.save_conversation(
                "mock-user",
                {**base, "title": "歌曲数据", "updatedAt": 2000},
            )

            sales = archive.list_conversations("sales-user")
            mock = archive.list_conversations("mock-user")
            self.assertEqual([item["title"] for item in sales], ["地区销售"])
            self.assertEqual([item["title"] for item in mock], ["歌曲数据"])

            archive.save_conversation(
                "sales-user",
                {**base, "title": "地区销售（更新）", "updatedAt": 3000},
            )
            self.assertEqual(
                archive.list_conversations("sales-user")[0]["title"],
                "地区销售（更新）",
            )

            self.assertTrue(archive.delete_conversation("sales-user", "conversation-1"))
            self.assertEqual(archive.list_conversations("sales-user"), [])
            self.assertEqual(len(archive.list_conversations("mock-user")), 1)

    def test_recommendation_reply_selects_recommended_clarification_option(self) -> None:
        result = QueryResult(
            task_id="task-metric",
            status="waiting_clarification",
            route="database_query",
            message="需要补充信息",
            clarification=Clarification(
                parameter="metric",
                question="请选择指标",
                reason="不同指标会产生不同结果",
                options=[
                    ClarificationOption(
                        id="paid_amount",
                        label="实付销售额",
                        description="按实付金额汇总",
                        recommended=True,
                    ),
                    ClarificationOption(
                        id="order_count",
                        label="订单量",
                        description="按订单数量统计",
                    ),
                ],
            ),
        )

        for reply in ("都行", "随便", "默认", "你推荐吧", "按推荐的"):
            with self.subTest(reply=reply):
                self.assertEqual(
                    SessionContext.match_clarification(reply, result),
                    "paid_amount",
                )

    def test_complete_turn_and_summary_survive_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sessions.db"
            archive = SessionArchive(path)
            result = {
                "task_id": "task-1",
                "status": "completed",
                "route": "database_query",
                "message": "查询完成",
                "sql": "SELECT 1",
                "columns": ["value"],
                "rows": [{"value": 1}],
                "analysis": "结果为1",
            }

            archive.save_turn("task-1", "s1", "查询数据", {"schema_fields": []}, result)
            archive.save_message("s1", "user", "查询数据", task_id="task-1")
            archive.save_message(
                "s1",
                "assistant",
                "结果为1",
                task_id="task-1",
                metadata={"status": "completed"},
            )
            archive.save_summary("s1", "历史摘要", {"task-1"})

            restored = SessionArchive(path)
            turn = restored.load_turns()[0]
            summary = restored.load_summaries()[0]
            messages = restored.load_messages("s1")

            self.assertEqual(turn["result"]["rows"], [{"value": 1}])
            self.assertEqual(turn["result"]["sql"], "SELECT 1")
            self.assertEqual(summary["summary"], "历史摘要")
            self.assertEqual(summary["summarized_ids"], {"task-1"})
            self.assertEqual([item["role"] for item in messages], ["user", "assistant"])
            self.assertEqual(messages[1]["metadata"]["status"], "completed")

    def test_session_context_restores_complete_turns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sessions.db"
            config = Settings(
                api_key="",
                session_archive_enabled=True,
                session_archive_path=str(path),
            )
            result = QueryResult(
                task_id="task-1",
                status="completed",
                route="data_qa",
                message="回答完成",
                analysis="这是完整回答",
            )

            first = SessionContext(NoopModel(), config)  # type: ignore[arg-type]
            first.remember("s1", result, "你好", {})
            restored = SessionContext(NoopModel(), config)  # type: ignore[arg-type]

            self.assertEqual(restored.tasks["task-1"]["query"], "你好")
            self.assertEqual(
                restored.tasks["task-1"]["result"].analysis,
                "这是完整回答",
            )
            self.assertEqual(restored.session_tasks["s1"], ["task-1"])

    def test_scoped_session_context_and_owner_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Settings(
                api_key="",
                session_archive_enabled=True,
                session_archive_path=str(Path(temp_dir) / "sessions.db"),
                short_term_summary_enabled=False,
            )
            result = QueryResult(
                task_id="task-follow-up",
                status="completed",
                route="database_query",
                message="查询完成",
                sql="SELECT region, SUM(paid_amount) FROM orders GROUP BY region",
                columns=["地区", "实付销售额"],
                rows=[{"地区": "华东", "实付销售额": 1}],
                standalone_query="统计2026年6月华东和华南各店铺的实付销售额",
            )
            session_id = "demo_current_sales:conversation-1"

            first = SessionContext(NoopModel(), config)  # type: ignore[arg-type]
            first.remember(
                session_id,
                result,
                "再按店铺拆分",
                {},
                user_id="demo_current_sales",
            )
            restored = SessionContext(NoopModel(), config)  # type: ignore[arg-type]

            self.assertEqual(
                restored.tasks["task-follow-up"]["user_id"],
                "demo_current_sales",
            )
            route_context = json.loads(restored.route_context(session_id))
            self.assertEqual(
                route_context["recent_turns"][0]["standalone_query"],
                "统计2026年6月华东和华南各店铺的实付销售额",
            )
            self.assertEqual(
                restored.recent_result_context(session_id)
                and json.loads(restored.recent_result_context(session_id))["sql"],
                result.sql,
            )

    def test_route_context_uses_only_six_recent_turns_without_summary(self) -> None:
        config = Settings(
            api_key="",
            session_archive_enabled=False,
            route_context_turns=6,
            short_term_summary_enabled=False,
        )
        context = SessionContext(NoopModel(), config)  # type: ignore[arg-type]
        for index in range(8):
            result = QueryResult(
                task_id=f"task-{index}",
                status="completed",
                route="data_qa",
                message="回答完成",
                analysis=f"回答-{index}",
            )
            context.remember("s1", result, f"问题-{index}", {})
        context.short_term_memory.restore("s1", "更早的历史摘要", {"task-0"})

        route_context = json.loads(context.route_context("s1"))
        memory_context = json.loads(context.short_term_context("s1"))

        self.assertEqual(len(route_context["recent_turns"]), 6)
        self.assertEqual(route_context["recent_turns"][0]["turn_id"], "task-2")
        self.assertNotIn("history_summary", route_context)
        self.assertEqual(memory_context["history_summary"], "更早的历史摘要")

    def test_route_context_keeps_resolved_query_for_multi_turn_follow_up(self) -> None:
        config = Settings(
            api_key="",
            session_archive_enabled=False,
            short_term_summary_enabled=False,
        )
        context = SessionContext(NoopModel(), config)  # type: ignore[arg-type]
        result = QueryResult(
            task_id="task-follow-up",
            status="completed",
            route="database_query",
            message="查询完成",
            standalone_query="统计2026年7月华东和华南地区的实付销售额",
            interpretation=Interpretation(
                metric="实付销售额",
                dimension="地区",
                time_range="2026年7月",
                table="订单",
                assumptions=[],
            ),
        )
        context.remember("s1", result, "只看华东和华南", {})

        recent = json.loads(context.route_context("s1"))["recent_turns"][0]
        self.assertEqual(
            recent["standalone_query"],
            "统计2026年7月华东和华南地区的实付销售额",
        )
        self.assertEqual(recent["interpretation"]["metric"], "实付销售额")
        self.assertEqual(recent["interpretation"]["time_range"], "2026年7月")


if __name__ == "__main__":
    unittest.main()
