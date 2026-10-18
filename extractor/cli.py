"""命令行入口。

用法（在项目根目录执行）：

    python -m extractor.cli --config extractor/configs/lc.yaml --input S2010.md --out result.json
    python -m extractor.cli --config extractor/configs/lc.yaml --dry-run

也支持直接运行脚本：python extractor/cli.py ...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # 允许 `python extractor/cli.py` 直接执行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "extractor"

from .core.config import load_config  # noqa: E402
from .core.errors import ConfigError, ExtractionError  # noqa: E402
from .core.llm import DEFAULT_BASE_URL, DEFAULT_MODEL, DashScopeClient  # noqa: E402
from .core.pipeline import extract  # noqa: E402
from .core.prompt import build_system_prompt  # noqa: E402
from .core.schema import compile_config  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m extractor.cli",
        description="配置驱动的文档信息抽取工具：换一份 YAML 配置即可抽取另一类文档。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", required=True, help="YAML 抽取配置路径")
    parser.add_argument("--input", help="待抽取的文档（MinerU 输出的 Markdown）")
    parser.add_argument("--out", help="结果 JSON 输出路径；缺省打印到标准输出")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="模型名称")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI 兼容接口地址")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="尝试使用 json_schema 严格模式（接口不支持时自动回退到 json_object）",
    )
    parser.add_argument("--retries", type=int, default=1, help="校验失败后的重试次数")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印 JSON Schema 与 System Prompt，不调用模型",
    )
    return parser


def _configure_stdio() -> None:
    """避免 Windows 控制台编码导致的 UnicodeEncodeError。"""

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = build_parser().parse_args(argv)

    if args.retries < 0:
        print("参数错误：--retries 不能为负数", file=sys.stderr)
        return 2

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    compiled = compile_config(config)

    if args.dry_run:
        print("=== JSON Schema ===")
        print(json.dumps(compiled.json_schema, ensure_ascii=False, indent=2))
        print()
        print("=== System Prompt ===")
        print(build_system_prompt(config, compiled.json_schema))
        return 0

    if not args.input:
        print("缺少参数：--input（或使用 --dry-run 只预览）", file=sys.stderr)
        return 2

    document_path = Path(args.input)
    if not document_path.is_file():
        print(f"输入文件不存在：{document_path}", file=sys.stderr)
        return 2

    try:
        document = document_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"无法读取输入文件 {document_path}：{exc}", file=sys.stderr)
        return 2

    if not document.strip():
        print(f"输入文件为空：{document_path}", file=sys.stderr)
        return 2

    try:
        client = DashScopeClient(model=args.model, base_url=args.base_url, strict=args.strict)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    try:
        result = extract(config, document, client, retries=args.retries)
    except ExtractionError as exc:
        print(f"抽取失败：{exc}", file=sys.stderr)
        return 1

    for note in client.notes:
        print(f"提示：{note}", file=sys.stderr)

    payload = {
        "result": result.data,
        "meta": {
            "config": str(Path(args.config)),
            "input": str(document_path),
            "model": result.model or args.model,
            "attempts": result.attempts,
            "usage": result.usage,
        },
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"已写入 {out_path}（尝试 {result.attempts} 次）", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
