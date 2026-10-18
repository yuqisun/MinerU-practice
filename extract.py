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