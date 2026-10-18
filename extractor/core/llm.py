"""模型调用层：对上层暴露一个极简的 ChatClient 协议，便于注入假实现做测试。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import OpenAI

from .errors import ConfigError

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.8-max"


@dataclass
class LLMResponse:
    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""


class ChatClient(Protocol):
    """所有模型客户端需要实现的最小接口。"""

    def complete(
        self,
        system: str,
        messages: list[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """返回一次补全结果；json_schema 仅供支持严格模式的客户端使用。"""
        ...


def _looks_like_format_rejection(exc: Exception) -> bool:
    """判断异常是否是"接口不支持 response_format/json_schema"这类参数拒绝。"""

    status = getattr(exc, "status_code", None)
    if status is not None and status != 400:
        return False
    text = str(exc).lower()
    markers = ("response_format", "json_schema", "json schema", "unsupported", "not support")
    return any(marker in text for marker in markers)


class DashScopeClient:
    """百炼（DashScope）OpenAI 兼容接口客户端。"""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        strict: bool = False,
        timeout: float = 180.0,
    ) -> None:
        key = api_key or os.getenv("DASHSCOPE_API_KEY")
        if not key:
            raise ConfigError(
                "未设置 DASHSCOPE_API_KEY 环境变量，无法调用模型。"
                "可执行 $env:DASHSCOPE_API_KEY = \"sk-...\" 后重试。"
            )
        self.model = model
        self.strict = strict
        self.notes: list[str] = []
        self._client = OpenAI(api_key=key, base_url=base_url, timeout=timeout)

    def complete(
        self,
        system: str,
        messages: list[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        payload = [{"role": "system", "content": system}, *messages]
        use_strict = self.strict and json_schema is not None

        try:
            completion = self._create(payload, json_schema if use_strict else None)
        except Exception as exc:  # noqa: BLE001 - 需要按接口能力做降级判断
            if not use_strict or not _looks_like_format_rejection(exc):
                raise
            self.strict = False
            self.notes.append(
                "当前接口不支持 json_schema 严格模式，已自动回退到 json_object。"
            )
            completion = self._create(payload, None)

        message = completion.choices[0].message
        usage: dict[str, Any] = {}
        if getattr(completion, "usage", None) is not None:
            try:
                usage = completion.usage.model_dump()
            except AttributeError:
                usage = {}
        return LLMResponse(
            text=message.content or "",
            usage=usage,
            model=getattr(completion, "model", self.model),
        )

    def _create(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any] | None,
    ) -> Any:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "extraction",
                    "strict": True,
                    "schema": json_schema,
                },
            }
        else:
            kwargs["response_format"] = {"type": "json_object"}
        return self._client.chat.completions.create(**kwargs)
