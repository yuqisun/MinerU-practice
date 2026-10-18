"""抽取编排：拼 Prompt → 调模型 → 解析 JSON → 校验 → 失败回灌重试。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from .config import SchemaConfig
from .errors import ExtractionError
from .llm import ChatClient
from .prompt import build_correction_message, build_system_prompt
from .schema import compile_config


@dataclass
class ExtractionResult:
    data: dict[str, Any]
    attempts: int
    raw_output: str
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


def strip_code_fences(text: str) -> str:
    """容错：去掉模型偶尔加上的 ```json 代码块包裹。"""

    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _summarize_validation_error(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "(根对象)"
        lines.append(f"- {location}: {error['msg']}")
    return "\n".join(lines)


def extract(
    config: SchemaConfig,
    document: str,
    client: ChatClient,
    *,
    retries: int = 1,
) -> ExtractionResult:
    """按配置抽取字段。

    retries 表示校验失败后额外重试的次数，总调用次数为 retries + 1。
    """

    if retries < 0:
        raise ValueError("retries 不能为负数")
    if not document.strip():
        raise ExtractionError("输入文档为空，无法抽取")

    compiled = compile_config(config)
    system_prompt = build_system_prompt(config, compiled.json_schema)
    messages: list[dict[str, str]] = [{"role": "user", "content": document}]

    last_error = "未知错误"
    attempts = 0

    for attempt in range(1, retries + 2):
        attempts = attempt
        response = client.complete(
            system_prompt, messages, json_schema=compiled.json_schema
        )
        raw_output = response.text or ""
        candidate = strip_code_fences(raw_output)

        if not candidate:
            last_error = "模型返回了空内容"
        else:
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError as exc:
                last_error = f"输出不是合法 JSON：{exc}"
            else:
                try:
                    validated = compiled.model.model_validate(payload)
                except ValidationError as exc:
                    last_error = _summarize_validation_error(exc)
                else:
                    return ExtractionResult(
                        data=validated.model_dump(),
                        attempts=attempt,
                        raw_output=raw_output,
                        model=response.model,
                        usage=response.usage,
                    )

        messages = [
            *messages,
            {"role": "assistant", "content": raw_output},
            {
                "role": "user",
                "content": build_correction_message(last_error, compiled.json_schema),
            },
        ]

    raise ExtractionError(
        f"抽取失败（已尝试 {attempts} 次）。最后一次错误：\n{last_error}"
    )
