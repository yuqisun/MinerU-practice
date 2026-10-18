"""配置加载与校验的测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from extractor.core.config import load_config
from extractor.core.errors import ConfigError

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


class ConfigTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def write_config(self, text: str) -> Path:
        path = self.tmp / "config.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def assert_config_error(self, text: str, needle: str) -> None:
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.write_config(text))
        self.assertIn(needle, str(ctx.exception))


class ValidConfigTests(ConfigTestCase):
    def test_loads_lc_config(self) -> None:
        config = load_config(CONFIG_DIR / "lc.yaml")
        self.assertEqual(config.name, "LCFields")
        self.assertEqual(
            set(config.fields),
            {"lc_number", "lc_amount", "lc_issuer", "swift_dc_number", "applicant"},
        )
        self.assertTrue(config.fields["lc_number"].required)
        self.assertFalse(config.fields["applicant"].required)
        self.assertEqual(len(config.fields["lc_number"].hints), 2)
        self.assertTrue(config.rules)

    def test_loads_invoice_config(self) -> None:
        config = load_config(CONFIG_DIR / "invoice.yaml")
        self.assertEqual(config.fields["currency"].enum, ["USD", "EUR", "CNY", "JPY"])
        items = config.fields["item_names"].items
        self.assertIsNotNone(items)
        assert items is not None
        self.assertEqual(items.type, "string")

    def test_default_value_is_kept(self) -> None:
        config = load_config(
            self.write_config(
                """
name: Demo
fields:
  note:
    type: string
    required: false
    description: 备注
    default: 无
"""
            )
        )
        self.assertEqual(config.fields["note"].default, "无")


class InvalidConfigTests(ConfigTestCase):
    def test_missing_description(self) -> None:
        self.assert_config_error(
            """
name: Demo
fields:
  a:
    type: string
""",
            "description",
        )

    def test_unknown_type(self) -> None:
        self.assert_config_error(
            """
name: Demo
fields:
  a:
    type: object
    description: 对象
""",
            "type",
        )

    def test_array_without_items(self) -> None:
        self.assert_config_error(
            """
name: Demo
fields:
  a:
    type: array
    description: 列表
""",
            "items",
        )

    def test_nested_array_rejected(self) -> None:
        self.assert_config_error(
            """
name: Demo
fields:
  a:
    type: array
    description: 二维数组
    items:
      type: array
      description: 内层
      items:
        type: string
        description: 元素
""",
            "二维数组",
        )

    def test_bad_field_name(self) -> None:
        self.assert_config_error(
            """
name: Demo
fields:
  1abc:
    type: string
    description: 非法字段名
""",
            "字段名",
        )

    def test_reserved_pydantic_name(self) -> None:
        self.assert_config_error(
            """
name: Demo
fields:
  copy:
    type: string
    description: 与 Pydantic 内置属性冲突
""",
            "Pydantic",
        )

    def test_enum_type_mismatch(self) -> None:
        self.assert_config_error(
            """
name: Demo
fields:
  a:
    type: integer
    description: 数字
    enum: [one, two]
""",
            "enum",
        )

    def test_default_on_required_field(self) -> None:
        self.assert_config_error(
            """
name: Demo
fields:
  a:
    type: string
    required: true
    description: 必填却有默认值
    default: x
""",
            "default",
        )

    def test_bad_yaml_syntax(self) -> None:
        self.assert_config_error("name: Demo\nfields: [unclosed\n", "YAML")

    def test_top_level_not_mapping(self) -> None:
        self.assert_config_error("- a\n- b\n", "顶层")

    def test_unknown_key_rejected(self) -> None:
        self.assert_config_error(
            """
name: Demo
fields:
  a:
    type: string
    description: 描述
    unknown_key: 1
""",
            "unknown_key",
        )

    def test_missing_file(self) -> None:
        with self.assertRaises(ConfigError):
            load_config(self.tmp / "nope.yaml")


if __name__ == "__main__":
    unittest.main()
