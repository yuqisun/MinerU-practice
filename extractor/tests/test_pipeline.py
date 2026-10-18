"""编排流程测试：用假客户端模拟模型，不需要 API Key。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from extractor.core.config import load_config
from extractor.core.errors import ExtractionError
from extractor.core.llm import LLMResponse
from extractor.core.pipeline import extract, strip_code_fences

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"

DOCUMENT = "信用证号码 LC-831-984398，金额 USD1,269,720.00，开证行 RESONA BANK, LTD., TOKYO。"

GOOD_JSON = json.dumps(
    {
        "lc_number": "LC-831-984398",
        "lc_amount": "USD1,269,720.00",
        "lc_issuer": "RESONA BANK, LTD., TOKYO",
        "swift_dc_number": None,
        "applicant": None,
    },
    ensure_ascii=False,
)


class StubClient:
    """按顺序返回预设文本；调用次数超过预设时重复最后一条。"""

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        system: str,
        messages: list[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {"system": system, "messages": messages, "json_schema": json_schema}
        )
        index = min(len(self.calls) - 1, len(self._texts) - 1)
        return LLMResponse(text=self._texts[index], usage={"total_tokens": 1}, model="stub")


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config(CONFIG_DIR / "lc.yaml")

    def test_success_on_first_attempt(self) -> None:
        client = StubClient([GOOD_JSON])
        result = extract(self.config, DOCUMENT, client)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.data["lc_number"], "LC-831-984398")
        self.assertEqual(len(client.calls), 1)

    def test_schema_passed_to_client(self) -> None:
        client = StubClient([GOOD_JSON])
        extract(self.config, DOCUMENT, client)
        schema = client.calls[0]["json_schema"]
        self.assertIsNotNone(schema)
        assert schema is not None
        self.assertEqual(set(schema["properties"]) & {"lc_number"}, {"lc_number"})

    def test_system_prompt_contains_field_hints(self) -> None:
        client = StubClient([GOOD_JSON])
        extract(self.config, DOCUMENT, client)
        system = client.calls[0]["system"]
        self.assertIn("SWIFT 报文", system)
        self.assertIn("交叉验证", system)

    def test_retry_after_invalid_json(self) -> None:
        client = StubClient(["这不是 JSON", GOOD_JSON])
        result = extract(self.config, DOCUMENT, client, retries=1)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(client.calls), 2)
        # 第二次请求应带上纠错消息
        second_messages = client.calls[1]["messages"]
        self.assertGreater(len(second_messages), len(client.calls[0]["messages"]))
        self.assertEqual(second_messages[-1]["role"], "user")
        self.assertIn("无法通过校验", second_messages[-1]["content"])

    def test_retry_after_missing_field(self) -> None:
        client = StubClient(['{"lc_number": "LC-1"}', GOOD_JSON])
        result = extract(self.config, DOCUMENT, client, retries=1)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.data["lc_issuer"], "RESONA BANK, LTD., TOKYO")

    def test_strips_markdown_code_fence(self) -> None:
        client = StubClient([f"```json\n{GOOD_JSON}\n```"])
        result = extract(self.config, DOCUMENT, client)
        self.assertEqual(result.data["lc_amount"], "USD1,269,720.00")

    def test_raises_after_exhausting_retries(self) -> None:
        client = StubClient(["{}", "{}"])
        with self.assertRaises(ExtractionError) as ctx:
            extract(self.config, DOCUMENT, client, retries=1)
        self.assertIn("已尝试 2 次", str(ctx.exception))
        self.assertEqual(len(client.calls), 2)

    def test_zero_retries_means_single_call(self) -> None:
        client = StubClient(["{}"])
        with self.assertRaises(ExtractionError):
            extract(self.config, DOCUMENT, client, retries=0)
        self.assertEqual(len(client.calls), 1)

    def test_empty_document_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            extract(self.config, "   ", StubClient([GOOD_JSON]))

    def test_negative_retries_rejected(self) -> None:
        with self.assertRaises(ValueError):
            extract(self.config, DOCUMENT, StubClient([GOOD_JSON]), retries=-1)


class StripFenceTests(unittest.TestCase):
    def test_plain_json_unchanged(self) -> None:
        self.assertEqual(strip_code_fences('{"a": 1}'), '{"a": 1}')

    def test_fence_with_language(self) -> None:
        self.assertEqual(strip_code_fences('```json\n{"a": 1}\n```'), '{"a": 1}')

    def test_fence_without_language(self) -> None:
        self.assertEqual(strip_code_fences('```\n{"a": 1}\n```'), '{"a": 1}')


if __name__ == "__main__":
    unittest.main()
