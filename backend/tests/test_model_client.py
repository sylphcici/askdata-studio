from __future__ import annotations

import unittest

from app.model_client import ModelClient


class SequencedModelClient(ModelClient):
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, float | None]] = []

    def chat(self, system: str, user: str, *, temperature: float | None = None) -> str:
        self.calls.append((system, temperature))
        return self.responses.pop(0)


class ModelClientJsonTest(unittest.TestCase):
    def test_extracts_json_object_surrounded_by_text(self) -> None:
        client = SequencedModelClient(['说明：{"ok": true}，以上。'])
        self.assertEqual(client.chat_json("system", "user"), {"ok": True})
        self.assertEqual(len(client.calls), 1)

    def test_retries_once_when_first_response_has_no_json(self) -> None:
        client = SequencedModelClient(["无法处理", '{"ok": true}'])
        self.assertEqual(client.chat_json("system", "user"), {"ok": True})
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[1][1], 0)
        self.assertIn("只能输出一个JSON对象", client.calls[1][0])


if __name__ == "__main__":
    unittest.main()
