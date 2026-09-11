from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import Lock
from typing import Any


class SessionArchive:
    """持久化保存完整会话轮次和摘要状态。"""

    def __init__(self, path: Path, *, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled
        self._lock = Lock()
        if enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    def save_turn(
        self,
        task_id: str,
        session_id: str,
        query: str,
        workspace: dict[str, Any],
        result: dict[str, Any],
        user_id: str = "demo_analyst",
    ) -> None:
        if not self.enabled:
            return
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO session_turns (
                    task_id, session_id, query, workspace_json, result_json, user_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    query = excluded.query,
                    workspace_json = excluded.workspace_json,
                    result_json = excluded.result_json,
                    user_id = excluded.user_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    task_id,
                    session_id,
                    query,
                    json.dumps(workspace, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    user_id,
                ),
            )

    def load_turns(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT task_id, session_id, query, workspace_json, result_json, user_id
                FROM session_turns
                ORDER BY created_at, rowid
                """
            ).fetchall()
        return [
            {
                "task_id": row[0],
                "session_id": row[1],
                "query": row[2],
                "workspace": json.loads(row[3]),
                "result": json.loads(row[4]),
                "user_id": row[5],
            }
            for row in rows
        ]

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO session_messages (
                    session_id, task_id, role, content, metadata_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    task_id,
                    role,
                    content,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )

    def load_messages(self, session_id: str) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT task_id, role, content, metadata_json
                FROM session_messages
                WHERE session_id = ?
                ORDER BY message_id
                """,
                (session_id,),
            ).fetchall()
        return [
            {
                "task_id": row[0],
                "role": row[1],
                "content": row[2],
                "metadata": json.loads(row[3]),
            }
            for row in rows
        ]

    def save_summary(
        self, session_id: str, summary: str, summarized_ids: set[str]
    ) -> None:
        if not self.enabled:
            return
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO session_summaries (
                    session_id, summary, summarized_ids_json
                ) VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    summary = excluded.summary,
                    summarized_ids_json = excluded.summarized_ids_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    session_id,
                    summary,
                    json.dumps(sorted(summarized_ids), ensure_ascii=False),
                ),
            )

    def load_summaries(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT session_id, summary, summarized_ids_json FROM session_summaries"
            ).fetchall()
        return [
            {
                "session_id": row[0],
                "summary": row[1],
                "summarized_ids": set(json.loads(row[2])),
            }
            for row in rows
        ]

    def save_conversation(self, user_id: str, conversation: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO ui_conversations (
                    user_id, conversation_id, title, updated_at_ms,
                    turns_json, workspace_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, conversation_id) DO UPDATE SET
                    title = excluded.title,
                    updated_at_ms = excluded.updated_at_ms,
                    turns_json = excluded.turns_json,
                    workspace_json = excluded.workspace_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    conversation["id"],
                    conversation["title"],
                    conversation["updatedAt"],
                    json.dumps(conversation.get("turns", []), ensure_ascii=False),
                    json.dumps(conversation.get("workspace", {}), ensure_ascii=False),
                ),
            )
            connection.execute(
                """
                DELETE FROM ui_conversations
                WHERE user_id = ? AND conversation_id NOT IN (
                    SELECT conversation_id FROM ui_conversations
                    WHERE user_id = ?
                    ORDER BY updated_at_ms DESC
                    LIMIT 30
                )
                """,
                (user_id, user_id),
            )

    def list_conversations(self, user_id: str) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT conversation_id, title, updated_at_ms, turns_json, workspace_json
                FROM ui_conversations
                WHERE user_id = ?
                ORDER BY updated_at_ms DESC
                LIMIT 30
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "title": row[1],
                "updatedAt": row[2],
                "turns": json.loads(row[3]),
                "workspace": json.loads(row[4]),
            }
            for row in rows
        ]

    def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        if not self.enabled:
            return False
        scoped_session_id = f"{user_id}:{conversation_id}"
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM ui_conversations WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            )
            connection.execute(
                "DELETE FROM session_messages WHERE session_id = ?",
                (scoped_session_id,),
            )
            connection.execute(
                "DELETE FROM session_summaries WHERE session_id = ?",
                (scoped_session_id,),
            )
            connection.execute(
                "DELETE FROM session_turns WHERE session_id = ? AND user_id = ?",
                (scoped_session_id, user_id),
            )
            return cursor.rowcount > 0

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS session_turns (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    workspace_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT 'demo_analyst',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_session_turns_session
                    ON session_turns(session_id, created_at);

                CREATE TABLE IF NOT EXISTS session_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    task_id TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_session_messages_session
                    ON session_messages(session_id, message_id);

                CREATE TABLE IF NOT EXISTS session_summaries (
                    session_id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    summarized_ids_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS ui_conversations (
                    user_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    turns_json TEXT NOT NULL,
                    workspace_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, conversation_id)
                );
                CREATE INDEX IF NOT EXISTS idx_ui_conversations_user_updated
                    ON ui_conversations(user_id, updated_at_ms DESC);
                """
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(session_turns)")
            }
            if "user_id" not in columns:
                connection.execute(
                    "ALTER TABLE session_turns "
                    "ADD COLUMN user_id TEXT NOT NULL DEFAULT 'demo_analyst'"
                )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)
