"""配置驱动的文档信息抽取工具。

用法见同目录 README.md 或 `python -m extractor.cli --help`。
"""

from .core.errors import ConfigError, ExtractionError

__all__ = ["ConfigError", "ExtractionError"]
__version__ = "0.1.0"
