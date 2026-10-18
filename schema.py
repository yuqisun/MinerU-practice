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