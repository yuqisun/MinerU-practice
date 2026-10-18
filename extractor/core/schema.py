"""把 YAML 配置编译成 JSON Schema（给模型看）和 Pydantic 模型（校验输出）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from .config import FieldSpec, SchemaConfig

_TYPE_MAP: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


def _python_type(spec: FieldSpec) -> Any:
    """把配置里的 type 映射为 Python / typing 类型。"""

    if spec.type == "array":
        assert spec.items is not None  # 已在配置校验中保证
        return list[_python_type(spec.items)]
    if spec.enum is not None:
        return Literal[tuple(spec.enum)]
    return _TYPE_MAP[spec.type]


def build_model(config: SchemaConfig) -> type[BaseModel]:
    """根据配置动态创建 Pydantic 模型。"""

    definitions: dict[str, Any] = {}
    for name, spec in config.fields.items():
        python_type = _python_type(spec)
        if spec.required:
            definitions[name] = (python_type, Field(description=spec.description))
        else:
            default = spec.default if "default" in spec.model_fields_set else None
            definitions[name] = (
                python_type | None,
                Field(default=default, description=spec.description),
            )
    return create_model(config.name, **definitions)


def _strip_titles(node: Any) -> Any:
    """去掉 Pydantic 自动生成的 title 等噪声，让 Schema 更短、更适合放进 Prompt。"""

    if isinstance(node, dict):
        return {key: _strip_titles(value) for key, value in node.items() if key != "title"}
    if isinstance(node, list):
        return [_strip_titles(item) for item in node]
    return node


def build_json_schema(config: SchemaConfig) -> dict[str, Any]:
    """生成随配置变化的 JSON Schema。"""

    return _strip_titles(build_model(config).model_json_schema())


@dataclass(frozen=True)
class CompiledSchema:
    """一次编译的产物，避免重复建模型。"""

    model: type[BaseModel]
    json_schema: dict[str, Any]


def compile_config(config: SchemaConfig) -> CompiledSchema:
    model = build_model(config)
    return CompiledSchema(model=model, json_schema=_strip_titles(model.model_json_schema()))
