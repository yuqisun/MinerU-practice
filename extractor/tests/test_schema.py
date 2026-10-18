"""配置 → JSON Schema / Pydantic 模型 / Prompt 的测试。

其中 test_structure_matches_existing_lcfields 是回归护栏：
新工具用 lc.yaml 生成的 Schema，必须和项目原有 schema.py 里的 LCFields 结构一致。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from extractor.core.config import load_config
from extractor.core.prompt import build_system_prompt
from extractor.core.schema import build_model, compile_config
from schema import LCFields  # 项目根目录下的原有实现，仅用于对照

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


def strip_titles(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: strip_titles(value) for key, value in node.items() if key != "title"}
    if isinstance(node, list):
        return [strip_titles(item) for item in node]
    return node


def non_null_branch(spec: dict[str, Any]) -> dict[str, Any]:
    """可选字段在 JSON Schema 里是 anyOf: [T, null]，取出其中 T 的部分。"""

    options = spec.get("anyOf")
    if not options:
        return spec
    branches = [option for option in options if option.get("type") != "null"]
    assert len(branches) == 1, f"预期恰好一个非 null 分支，实际：{options!r}"
    merged = dict(branches[0])
    if "description" in spec:
        merged.setdefault("description", spec["description"])
    return merged


class LcSchemaRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config(CONFIG_DIR / "lc.yaml")
        cls.generated = compile_config(cls.config).json_schema
        cls.reference = strip_titles(LCFields.model_json_schema())

    def test_property_names_match(self) -> None:
        self.assertEqual(
            set(self.generated["properties"]), set(self.reference["properties"])
        )

    def test_required_matches(self) -> None:
        self.assertEqual(
            set(self.generated.get("required", [])),
            set(self.reference.get("required", [])),
        )

    def test_field_types_match(self) -> None:
        for name, reference_spec in self.reference["properties"].items():
            generated_spec = self.generated["properties"][name]
            self.assertEqual(
                generated_spec.get("type"), reference_spec.get("type"), f"字段 {name}"
            )
            self.assertEqual(
                generated_spec.get("anyOf"), reference_spec.get("anyOf"), f"字段 {name}"
            )

    def test_optional_fields_are_nullable(self) -> None:
        for name in ("swift_dc_number", "applicant"):
            spec = self.generated["properties"][name]
            self.assertIn({"type": "null"}, spec["anyOf"])


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config(CONFIG_DIR / "lc.yaml")
        cls.model = build_model(cls.config)

    def test_valid_payload(self) -> None:
        instance = self.model.model_validate(
            {
                "lc_number": "LC-1",
                "lc_amount": "USD1.00",
                "lc_issuer": "BANK",
                "swift_dc_number": None,
                "applicant": None,
            }
        )
        self.assertEqual(instance.model_dump()["lc_number"], "LC-1")

    def test_missing_required_field_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.model.model_validate({"lc_amount": "USD1.00", "lc_issuer": "BANK"})

    def test_optional_field_defaults_to_none(self) -> None:
        instance = self.model.model_validate(
            {"lc_number": "LC-1", "lc_amount": "USD1.00", "lc_issuer": "BANK"}
        )
        self.assertIsNone(instance.model_dump()["applicant"])

    def test_wrong_type_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.model.model_validate(
                {"lc_number": 123, "lc_amount": "USD1.00", "lc_issuer": "BANK"}
            )


class InvoiceSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config(CONFIG_DIR / "invoice.yaml")
        cls.compiled = compile_config(cls.config)

    def test_enum_compiled(self) -> None:
        currency = non_null_branch(self.compiled.json_schema["properties"]["currency"])
        self.assertEqual(currency["enum"], ["USD", "EUR", "CNY", "JPY"])

    def test_array_compiled(self) -> None:
        items = non_null_branch(self.compiled.json_schema["properties"]["item_names"])
        self.assertEqual(items["type"], "array")
        self.assertEqual(items["items"]["type"], "string")

    def test_enum_enforced_by_model(self) -> None:
        with self.assertRaises(ValidationError):
            self.compiled.model.model_validate(
                {
                    "invoice_number": "INV-1",
                    "invoice_date": "2026-01-01",
                    "seller": "ACME",
                    "total_amount": "USD 1.00",
                    "currency": "GBP",
                }
            )

    def test_array_items_validated(self) -> None:
        instance = self.compiled.model.model_validate(
            {
                "invoice_number": "INV-1",
                "invoice_date": "2026-01-01",
                "seller": "ACME",
                "total_amount": "USD 1.00",
                "item_names": ["螺丝", "螺母"],
            }
        )
        self.assertEqual(instance.model_dump()["item_names"], ["螺丝", "螺母"])


class PromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config(CONFIG_DIR / "lc.yaml")
        cls.schema = compile_config(cls.config).json_schema
        cls.prompt = build_system_prompt(cls.config, cls.schema)

    def test_contains_field_descriptions(self) -> None:
        for name, spec in self.config.fields.items():
            self.assertIn(name, self.prompt)
            self.assertIn(spec.description, self.prompt)

    def test_contains_hints_and_rules(self) -> None:
        for hint in self.config.fields["lc_number"].hints:
            self.assertIn(hint, self.prompt)
        for rule in self.config.rules:
            self.assertIn(rule, self.prompt)

    def test_contains_json_schema_and_json_keyword(self) -> None:
        self.assertIn('"lc_number"', self.prompt)
        self.assertIn("JSON", self.prompt)

    def test_marks_optional_fields(self) -> None:
        self.assertIn("可选", self.prompt)
        self.assertIn("必填", self.prompt)


if __name__ == "__main__":
    unittest.main()
