# extractor —— 配置驱动的文档信息抽取工具

把原本硬编码在 `schema.py` + `extract.py` 里的抽取逻辑抽象出一层：

- **领域知识下沉到 YAML**：抽哪些字段、字段含义、去哪找、有哪些全局规则，全部写在配置文件里；
- **工具代码与业务无关**：换一份配置就能抽另一类文档（信用证、发票、合同……），Python 代码一行不改；
- **可测试**：模型调用被抽象成 `ChatClient` 协议，单元测试用假客户端跑，不需要 API Key。

> 本目录是**新增**的独立工具，不修改项目原有的 `schema.py`、`extract.py` 和根 `README.md`，两者可以并存。

## 1. 目录结构

```
extractor/
├─ cli.py                  # 命令行入口
├─ configs/
│  ├─ lc.yaml              # 信用证配置（等价于原 LCFields + 原 Prompt 里的规则）
│  └─ invoice.yaml         # 发票配置（演示"换配置即换任务"）
├─ core/
│  ├─ config.py            # 读 YAML + 元模型校验
│  ├─ schema.py            # 配置 → JSON Schema / Pydantic 动态模型
│  ├─ prompt.py            # 配置 → System Prompt / 纠错 Prompt
│  ├─ llm.py               # 百炼 OpenAI 兼容客户端（含严格模式回退）
│  ├─ pipeline.py          # 编排：调用 → 解析 → 校验 → 重试
│  └─ errors.py            # ConfigError / ExtractionError
└─ tests/                  # unittest，44 个用例
```

## 2. 快速开始

在**项目根目录**执行：

```powershell
# 1) 先预览：只生成 JSON Schema 和 System Prompt，不调用模型、不需要 API Key
python -m extractor.cli --config extractor/configs/lc.yaml --dry-run

# 2) 设置 API Key（仅当前会话有效）
$env:DASHSCOPE_API_KEY = "sk-你的APIKey"

# 3) 正式抽取，结果写入文件
python -m extractor.cli --config extractor/configs/lc.yaml --input S2010.md --out result.json

# 4) 换一份配置抽发票，代码无需改动
python -m extractor.cli --config extractor/configs/invoice.yaml --input invoice.md
```

也可以直接运行脚本：`python extractor/cli.py --config ... --dry-run`。

输出结构：

```json
{
  "result": { "lc_number": "...", "lc_amount": "...", "lc_issuer": "..." },
  "meta": {
    "config": "extractor/configs/lc.yaml",
    "input": "S2010.md",
    "model": "qwen3.8-max",
    "attempts": 1,
    "usage": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 }
  }
}
```

## 3. 配置格式（YAML）

```yaml
name: LCFields                 # 模型名，需是合法标识符
description: 从信用证 PDF 中抽取的字段

rules:                         # 全局抽取规则，原样进入 Prompt
  - 文档中没有的字段填 null，不要编造。

fields:
  lc_number:                   # 字段名（输出 JSON 的 key）
    type: string               # string / integer / number / boolean / array
    required: true             # 是否必填，默认 true
    description: 信用证号码，例如 LC-831-984398
    hints:                     # 可选：去哪找、怎么判断
      - '也可能出现在 SWIFT 报文的 "20: Documentary Credit Number" 字段'
```

### 顶层键

| 键 | 必填 | 说明 |
|---|---|---|
| `name` | 否 | 模型名，默认 `Extraction` |
| `description` | 否 | 任务描述，仅作文档用途 |
| `rules` | 否 | 全局规则列表，逐条写入 Prompt |
| `fields` | 是 | 字段定义，至少一个 |

### 字段键

| 键 | 必填 | 说明 |
|---|---|---|
| `type` | 是 | `string` / `integer` / `number` / `boolean` / `array` |
| `description` | 是 | 字段含义（会进入 JSON Schema 和 Prompt） |
| `required` | 否 | 默认 `true`；`false` 表示可为空，Schema 中类型自动变成 `T \| null` |
| `hints` | 否 | 定位提示列表，例如"通常在表格第 2 页" |
| `enum` | 否 | 限定取值（仅标量类型） |
| `examples` | 否 | 示例值 |
| `default` | 否 | 默认值（不可与 `required: true` 同时出现） |
| `items` | 否 | 仅 `type: array` 使用，描述元素类型 |

### YAML 小提示

标量里出现 `: `（冒号加空格）必须整体加引号，否则 YAML 会把它当成新的键值对，例如：

```yaml
description: 'SWIFT 报文中 "20: Documentary Credit Number" 字段的值'
```

## 4. 工作原理

```
lc.yaml ──► SchemaConfig 元模型校验 ──► 动态 Pydantic 模型 ──► JSON Schema ──► Prompt
                                              └──────────────► 校验模型输出
```

1. `config.py` 先用 Pydantic 校验配置本身，错误定位到 `fields.x.type` 这一级；
2. `schema.py` 用 `create_model()` 按配置建模型，再由 `model_json_schema()` 生成 Schema，保证"给模型看的结构"和"校验用的结构"同源；
3. `prompt.py` 拼出 System Prompt：Schema + 每个字段的说明/类型/必填/取值/提示 + 全局规则；
4. `pipeline.py` 调用模型，解析 JSON，用动态模型校验；失败则把错误回灌给模型重试（默认 1 次）。

## 5. 命令行参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--config` | 必填 | YAML 配置路径 |
| `--input` | 无 | 待抽取的 Markdown（`--dry-run` 时可省略） |
| `--out` | 打印到 stdout | 结果 JSON 路径，目录会自动创建 |
| `--model` | `qwen3.8-max` | 模型名称 |
| `--base-url` | 百炼兼容接口 | OpenAI 兼容接口地址 |
| `--strict` | 关闭 | 尝试 `json_schema` 严格模式，接口不支持时自动回退并提示 |
| `--retries` | `1` | 校验失败后的重试次数（总调用次数 = retries + 1） |
| `--dry-run` | 关闭 | 只打印 Schema 与 Prompt，不调用模型 |

退出码：`0` 成功；`1` 抽取失败（重试后仍不合法）；`2` 参数或配置错误。

## 6. 测试

```powershell
python -m unittest discover -s extractor/tests -t . -v
```

覆盖：配置校验（非法类型、保留字段名、数组嵌套、YAML 语法错误等）、Schema 编译（与原 `LCFields` 结构回归对比）、Prompt 内容、编排流程（首次成功、非法 JSON 重试、缺字段重试、重试耗尽、代码块清洗）。

## 7. 已知限制

- 不支持嵌套 `object` 字段与二维数组（配置会明确报错），需要时再扩展；
- 默认仍用 `json_object` 模式：保证输出是合法 JSON，但结构靠 Prompt 约束，极端情况下可能缺字段（会自动重试）；
- `--strict` 依赖百炼兼容接口对 `json_schema` 的支持，未实测前建议保持关闭；可选字段（`T | null`）也可能不符合部分平台的严格模式要求；
- 单次请求把整篇文档放进 Prompt，未做分块/截断，超长文档需要另行切分。
