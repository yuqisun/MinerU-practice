# MinerU 练习环境搭建（Windows / PowerShell）

## 1. 创建项目文件夹并进入

```powershell
mkdir D:\work\MinerU-practice
cd D:\work\MinerU-practice
```

## 2. 创建虚拟环境

```powershell
python -m venv .venv
```

## 3. 激活虚拟环境

```powershell
.\.venv\Scripts\activate.ps1
```

激活成功后，命令行提示符前会出现 `(.venv)`。

## 4. 安装 MinerU

```powershell
pip install -U "mineru[core]"
```

如果下载慢，可使用清华镜像：

```powershell
pip install -U "mineru[core]" -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 说明：Windows 原生环境建议先装 `core`，避免 `all` 中 vLLM 等 Linux 依赖安装失败。

## 5. 验证安装

```powershell
mineru --version
```

当前环境输出示例：

```text
MinerU version: 4.0.12
Python version: 3.12.7
```

## 6. 使用 MinerU 解析 PDF

将待解析的 PDF 文件（如 `S2010.pdf`）放到项目目录 `D:\work\MinerU-practice` 下。

### 6.1 设置模型下载源（可选，国内推荐）

首次运行需要下载模型，为加快速度，可先切换为 ModelScope 源：

```powershell
$env:MINERU_MODEL_SOURCE = "modelscope"
```

### 6.2 执行解析命令

```powershell
mineru-kit parse S2010.pdf -o S2010.md --tier standard
```

**参数说明**：

| 参数 | 含义 |
|---|---|
| `S2010.pdf` | 输入文件路径 |
| `-o S2010.md` | 输出 Markdown 文件 |
| `--tier standard` | 解析档位，使用 Hybrid 模式（传统小模型 + VLM 大模型） |

> `--tier` 可选 `basic`（纯 Pipeline 小模型）、`standard`（Hybrid，推荐）、`advanced`（更偏向 VLM 高精度）。

### 6.3 首次运行会下载模型

首次执行会自动下载两套模型：

- **`MinerU-4_models_onnx`**：传统小模型包（ONNX 格式），包含版面分析、OCR、公式识别、表格识别等，用于 Pipeline 流程，零幻觉、CPU 友好。
- **`MinerU2.5-Pro-2605-1.2B-GGUF`**：视觉语言大模型（GGUF 格式），用于 VLM 端到端解析，精度更高，由 llama.cpp 推理。

模型下载完成后缓存在 `~/.mineru/models`，后续解析不再重复下载。

### 6.4 解析日志示例

```text
2026-10-16 23:44:12,072 | INFO    | modelscope_hub.download | Downloading 1 files from OpenDataLab/MinerU-4_models_onnx@master
...
2026-10-16 23:44:28.096 | INFO     | mineru.model.vlm.selector:get_vlm_engine:61 - Using llama-cpp-engine as the inference engine for VLM.
...
2026-10-16 23:45:05.969 | INFO     | mineru.backend.analysis.pdf.window:_log_processing_window_plan:105 - Hybrid processing-window run. page_count=6, window_size=64, total_windows=1
...
Layout Predict: 100%|██████████████████████████████████████████████████| 6/6 [00:04<00:00,  1.34it/s]
VLM Predict: 100%|███████████████████████████████████████████████████| 58/58 [12:58<00:00, 13.43s/it]
OCR-det: 100%|████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 29/29 [00:00<00:00, 62.55it/s]
2026-10-16 23:58:12.273 | INFO     | mineru.backend.analyze:_log_infer_performance:26 - model_list infer finished, file_suffix=pdf, pages=6, cost=786.264086s, speed=0.008 page/s
Parsed 1 input(s).
```

解析完成后，当前目录会生成 `S2010.md`。

## 8. 定义抽取 Schema

使用 Pydantic 定义要从信用证 PDF 中抽取的字段，既保证类型安全，也方便后续将 JSON Schema 传给大模型。

### 8.1 安装 Pydantic

```powershell
pip install "pydantic>=2.0"
```

### 8.2 创建 `schema.py`

在项目目录 `D:\work\MinerU-practice` 下创建 `schema.py`：

```python
from pydantic import BaseModel, Field
from typing import Optional


class LCFields(BaseModel):
    """从信用证 PDF 中抽取的字段"""

    lc_number: str = Field(
        description="信用证号码，例如 LC-831-984398。可能出现在银行通知书的表格里，也可能出现在 SWIFT 报文的 '20: Documentary Credit Number' 字段。"
    )
    lc_amount: str = Field(
        description="信用证金额，含币种，例如 USD1,269,720.00。"
    )
    lc_issuer: str = Field(
        description="开证方（开证银行）名称，例如 RESONA BANK, LTD., TOKYO。"
    )
    swift_dc_number: Optional[str] = Field(
        default=None,
        description="SWIFT 报文中 '20: Documentary Credit Number' 字段的值。通常与 lc_number 相同。"
    )
    applicant: Optional[str] = Field(
        default=None,
        description="SWIFT 报文中 '50: Applicant' 字段的值，即开证申请人名称和地址。"
    )
```

### 8.3 字段说明

| 字段 | 类型 | 是否必填 | 来源 |
|---|---|---|---|
| `lc_number` | str | 是 | 第 2 页表格 / 第 3 页 SWIFT 字段 20 |
| `lc_amount` | str | 是 | 第 1 页 / 第 2 页表格 / 第 3 页字段 32B |
| `lc_issuer` | str | 是 | 第 1 页 / 第 2 页表格 |
| `swift_dc_number` | str | 否 | 第 3 页字段 20 |
| `applicant` | str | 否 | 第 3 页字段 50 |

> **为什么 `lc_number` 和 `swift_dc_number` 分开？**
> 你列了两个来源（银行通知书表格 + SWIFT 字段 20），分开抽取可以交叉验证。
> 如果两者一致，说明解析和抽取都可靠；如果不一致，就值得人工复查。

## 9. 使用百炼 API 调用 Qwen3.8-Max 抽取字段

百炼平台兼容 OpenAI 接口，使用 OpenAI Python SDK 即可调用 Qwen3.8-Max[reference:0]。

### 9.1 安装 OpenAI SDK

```powershell
pip install openai
```

### 9.2 准备 API Key

在百炼控制台创建 API Key 后，在 PowerShell 中设置环境变量（当前会话有效）：

```powershell
$env:DASHSCOPE_API_KEY = "sk-你的APIKey"
```

> API Key 按地域绑定，调用北京地域的 base_url 必须使用在北京地域创建的 API Key[reference:1]。

### 9.3 创建抽取脚本 `extract.py`

在项目目录 `D:\work\MinerU-practice` 下创建 `extract.py`：

```python
import os
import json
from openai import OpenAI
from schema import LCFields

# 初始化客户端
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# 读取 MinerU 解析结果
with open("S2010.md", "r", encoding="utf-8") as f:
    document_text = f.read()

# 从 Pydantic 模型生成 JSON Schema
json_schema = LCFields.model_json_schema()

# 构造 System Prompt
system_prompt = f"""你是一个专业的文档信息抽取助手。
从给定的文档中抽取以下字段，严格按照 JSON Schema 格式输出：

{json.dumps(json_schema, ensure_ascii=False, indent=2)}

抽取规则：
1. lc_number：信用证号码，可能出现在银行通知书表格中，也可能出现在 SWIFT 报文的 "20: Documentary Credit Number" 字段。
2. lc_amount：信用证金额，必须包含币种，如 USD1,269,720.00。
3. lc_issuer：开证方（开证银行）名称。
4. swift_dc_number：SWIFT 报文中 "20: Documentary Credit Number" 字段的值，如果文档中没有则留空。
5. applicant：SWIFT 报文中 "50: Applicant" 字段的值，即开证申请人名称和地址，如果文档中没有则留空。

只输出 JSON，不要包含任何额外文字。"""

# 调用模型
response = client.chat.completions.create(
    model="qwen3.8-max",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": document_text},
    ],
    response_format={"type": "json_object"},
)

# 解析结果并用 Pydantic 校验
result_text = response.choices[0].message.content
print("原始输出：")
print(result_text)

fields = LCFields.model_validate_json(result_text)
print("\n校验通过，结构化结果：")
print(fields.model_dump_json(indent=2))
```

**代码说明**：

| 部分 | 作用 |
|---|---|
| `LCFields.model_json_schema()` | 从 Pydantic 模型自动生成 JSON Schema |
| `response_format={"type": "json_object"}` | 强制模型输出合法 JSON 字符串[reference:2] |
| `LCFields.model_validate_json()` | 用 Pydantic 校验 LLM 输出是否符合 Schema |

> **关于 `json_object` 模式**：它保证输出是合法 JSON，但不强制遵循特定结构，因此 System Prompt 中需要显式描述字段和规则[reference:3]。Qwen3.8-Max 支持更严格的 `json_schema` 模式，但需要确认当前 SDK 版本是否已支持，后续可升级。

### 9.4 执行抽取

```powershell
python extract.py
```

**预期输出**：

```json
{
  "lc_number": "LC-831-984398",
  "lc_amount": "USD1,269,720.00",
  "lc_issuer": "RESONA BANK, LTD., TOKYO",
  "swift_dc_number": "LC-831-984398",
  "applicant": "DAITO CO., LTD. 1-29 3CHOME KYUTAROMACHI CHUO-KU OSAKA 541-0056, JAPAN"
}
```

### 9.5 可能遇到的问题

| 问题 | 原因 | 解决 |
|---|---|---|
| `401 invalid_api_key` | API Key 与 base_url 地域不匹配 | 确认 API Key 与 base_url 在同一地域创建[reference:4] |
| `400 messages must contain 'json'` | `json_object` 模式要求 Prompt 中出现 "JSON" 字样 | System Prompt 中已包含 "JSON Schema" 和 "只输出 JSON"，通常不会触发[reference:5] |
| 输出缺少字段 | 模型未严格遵循 Schema | 当前用 `json_object` 模式，可后续切换到 `json_schema` 严格模式，或增加 Few-shot 示例 |
| 输出包含 ```json 代码块 | 模型自行添加了 Markdown 包裹 | `json_object` 模式已抑制此行为；若仍出现，可在解析前做字符串清洗[reference:6] |