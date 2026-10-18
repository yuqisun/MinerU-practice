"""由配置生成 System Prompt 与纠错 Prompt。

Prompt 里不含任何领域硬编码：字段说明来自 description / hints / enum / examples，
全局规则来自配置顶层的 rules。换一份配置即换一个抽取任务。
"""

from __future__ import annotations

import json
from typing import Any

from .config import FieldSpec, SchemaConfig

_TYPE_LABEL = {
    "string": "字符串",
    "integer": "整数",
    "number": "数字",
    "boolean": "布尔值",
    "array": "数组",
}


def _describe_field(spec: FieldSpec) -> str:
    parts = [f"类型：{_TYPE_LABEL[spec.type]}"]
    if spec.type == "array" and spec.items is not None:
        parts.append(f"元素类型：{_TYPE_LABEL[spec.items.type]}")
    parts.append("必填" if spec.required else "可选")
    if spec.enum:
        parts.append("取值必须是：" + " / ".join(str(value) for value in spec.enum))
    if spec.examples:
        parts.append("示例：" + "；".join(str(value) for value in spec.examples))
    if spec.hints:
        parts.append("定位提示：" + "；".join(spec.hints))
    if not spec.required:
        parts.append("文档中没有该信息时填 null")
    return "，".join(parts)


def build_system_prompt(config: SchemaConfig, json_schema: dict[str, Any]) -> str:
    """组装抽取指令。注意必须出现 "JSON" 字样，json_object 模式依赖它。"""

    schema_text = json.dumps(json_schema, ensure_ascii=False, indent=2)

    lines = [
        "你是一个专业的文档信息抽取助手。",
        "请从用户提供的文档中抽取字段，并严格按照下面的 JSON Schema 输出：",
        "",
        schema_text,
        "",
        "字段说明：",
    ]
    for index, (name, spec) in enumerate(config.fields.items(), start=1):
        lines.append(f"{index}. `{name}`：{spec.description}（{_describe_field(spec)}）")

    if config.rules:
        lines.extend(["", "抽取规则："])
        lines.extend(f"- {rule}" for rule in config.rules)

    lines.extend(
        [
            "",
            "只输出一个 JSON 对象，不要包含任何额外文字，不要使用 Markdown 代码块。",
        ]
    )
    return "\n".join(lines)


def build_correction_message(error_text: str, json_schema: dict[str, Any]) -> str:
    """校验失败后回灌给模型的纠错指令。"""

    schema_text = json.dumps(json_schema, ensure_ascii=False, indent=2)
    return (
        "上一次输出无法通过校验：\n"
        f"{error_text}\n\n"
        "请重新输出一个完整的 JSON 对象，严格遵守下面的 JSON Schema：\n"
        f"{schema_text}\n\n"
        "不要输出解释、道歉或 Markdown 代码块。"
    )
