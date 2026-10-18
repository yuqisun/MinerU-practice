"""工具内部共用的异常类型。"""

from __future__ import annotations


class ExtractorError(Exception):
    """本工具所有可预期错误的基类。"""


class ConfigError(ExtractorError):
    """用户配置（YAML）或运行参数不合法。"""


class ExtractionError(ExtractorError):
    """调用模型或校验模型输出失败。"""
