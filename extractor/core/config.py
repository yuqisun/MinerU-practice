"""加载并校验用户提供的 YAML 抽取配置。

配置是工具唯一的"领域知识入口"：字段、类型、是否必填、描述、定位提示、
全局抽取规则都写在 YAML 里，Python 代码不含任何信用证相关的硬编码。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .errors import ConfigError

SCALAR_TYPES = ("string", "integer", "number", "boolean")
ALL_TYPES = (*SCALAR_TYPES, "array")

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _enum_value_matches(value: Any, type_name: str) -> bool:
    """判断 enum / default 中的值是否与声明的类型一致。"""

    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    return False


class FieldSpec(BaseModel):
    """单个可抽取字段的定义。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["string", "integer", "number", "boolean", "array"]
    required: bool = True
    description: str
    hints: list[str] = Field(default_factory=list)
    enum: list[Any] | None = None
    examples: list[Any] | None = None
    default: Any | None = None
    items: "FieldSpec | None" = None

    @field_validator("description")
    @classmethod
    def _check_description(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("description 不能为空，请说明该字段是什么")
        return text

    @field_validator("hints")
    @classmethod
    def _clean_hints(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]

    @model_validator(mode="after")
    def _check_consistency(self) -> "FieldSpec":
        if self.type == "array":
            if self.items is None:
                raise ValueError("type 为 array 时必须提供 items（数组元素类型）")
            if self.items.type == "array":
                raise ValueError("暂不支持二维数组：items.type 不能是 array")
        elif self.items is not None:
            raise ValueError("只有 type 为 array 的字段才能设置 items")

        if self.enum is not None:
            if self.type == "array":
                raise ValueError("enum 暂不支持 array 类型")
            if not self.enum:
                raise ValueError("enum 不能是空列表")
            invalid = [v for v in self.enum if not _enum_value_matches(v, self.type)]
            if invalid:
                raise ValueError(
                    f"enum 中的值 {invalid!r} 与 type: {self.type} 不匹配"
                )

        if self.required and "default" in self.model_fields_set:
            raise ValueError("required 为 true 的字段不能同时设置 default")

        if not self.required and "default" in self.model_fields_set:
            default = self.default
            if default is not None:
                if not _enum_value_matches(default, self.type):
                    raise ValueError(
                        f"default {default!r} 与 type: {self.type} 不匹配"
                    )
                if self.enum is not None and default not in self.enum:
                    raise ValueError(f"default {default!r} 不在 enum 中")
        return self


class SchemaConfig(BaseModel):
    """一份完整的抽取配置。"""

    model_config = ConfigDict(extra="forbid")

    name: str = "Extraction"
    description: str = ""
    rules: list[str] = Field(default_factory=list)
    fields: dict[str, FieldSpec]

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        text = value.strip()
        if not _IDENT_RE.match(text):
            raise ValueError("name 只能包含字母、数字、下划线，且不能以数字开头")
        if len(text) > 64:
            raise ValueError("name 长度不能超过 64 个字符")
        return text

    @field_validator("rules")
    @classmethod
    def _clean_rules(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]

    @model_validator(mode="after")
    def _check_fields(self) -> "SchemaConfig":
        if not self.fields:
            raise ValueError("fields 不能为空，至少定义一个字段")
        for name in self.fields:
            if not _IDENT_RE.match(name):
                raise ValueError(
                    f"字段名 {name!r} 不合法：只能包含字母、数字、下划线，且不能以数字开头"
                )
            if name.startswith("model_"):
                raise ValueError(f"字段名 {name!r} 不能以 model_ 开头（与 Pydantic 保留前缀冲突）")
            if hasattr(BaseModel, name):
                raise ValueError(f"字段名 {name!r} 与 Pydantic 内置属性同名，请换一个名字")
        return self


def _format_validation_error(exc: ValidationError, source: Path) -> str:
    lines = [f"配置文件 {source} 校验失败："]
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        message = error["msg"].removeprefix("Value error, ")
        lines.append(f"  - {location}: {message}" if location else f"  - {message}")
    return "\n".join(lines)


def load_config(path: str | Path) -> SchemaConfig:
    """读取并校验 YAML 配置，失败时抛出带定位信息的 ConfigError。"""

    source = Path(path)
    if not source.is_file():
        raise ConfigError(f"配置文件不存在：{source}")

    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {source}：{exc}") from exc

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 解析失败：{source}\n{exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件 {source} 的顶层必须是映射（key: value）")

    try:
        return SchemaConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc, source)) from exc
