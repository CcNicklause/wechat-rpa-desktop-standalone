from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.app.core.security import validate_phone


class LeadStatus(StrEnum):
    NEW_LEAD = 'NEW_LEAD'
    CALLING = 'CALLING'
    INTENT_CONFIRMED = 'INTENT_CONFIRMED'
    RPA_PENDING_APPROVAL = 'RPA_PENDING_APPROVAL'
    RPA_SIMULATED = 'RPA_SIMULATED'
    RPA_EXECUTING = 'RPA_EXECUTING'
    WECHAT_ADD_REQUESTED = 'WECHAT_ADD_REQUESTED'
    WECHAT_ACCEPTED = 'WECHAT_ACCEPTED'
    RPA_BLOCKED = 'RPA_BLOCKED'
    RPA_FAILED = 'RPA_FAILED'
    # 业务终态（区别于 RPA_FAILED 系统失败）：链路读屏判定出的正常业务结果
    WECHAT_TARGET_NOT_FOUND = 'WECHAT_TARGET_NOT_FOUND'   # 搜不到账号
    WECHAT_ALREADY_FRIEND = 'WECHAT_ALREADY_FRIEND'       # 已是好友
    WECHAT_ADD_REJECTED = 'WECHAT_ADD_REJECTED'           # 对方拒绝/限制添加
    WECHAT_RISK_CONTROL = 'WECHAT_RISK_CONTROL'           # 触发风控，已熔断
    WECHAT_ACCEPTANCE_EXHAUSTED = 'WECHAT_ACCEPTANCE_EXHAUSTED'  # 复查上限达到，停止轮询


class LeadCreateRequest(BaseModel):
    customer_name: str = Field(min_length=1, max_length=64)
    company: str = Field(min_length=1, max_length=128)
    phone: str = Field(min_length=5, max_length=32)
    sales_id: str = Field(default='sales_demo_001', min_length=1, max_length=64)

    @field_validator('phone')
    @classmethod
    def phone_is_valid(cls, value: str) -> str:
        return validate_phone(value)


class LeadResponse(BaseModel):
    lead_id: str
    customer_name: str
    company: str
    phone_masked: str
    sales_id: str
    status: LeadStatus


class CallSummaryRequest(BaseModel):
    intent: Literal['STRONG', 'FOLLOW_UP', 'REJECTED']
    summary: str = Field(min_length=1, max_length=1000)
    customer_consent: bool
    sales_confirmed_call: bool
    consent_evidence: str = Field(default='', max_length=500)


class CallSummaryResponse(BaseModel):
    lead_id: str
    status: LeadStatus
    next_action: str | None = None


class LeadStatsResponse(BaseModel):
    """Statistics for leads grouped by status categories."""
    total: int = 0
    success: int = 0  # WECHAT_ACCEPTED, WECHAT_ALREADY_FRIEND
    running: int = 0  # CALLING, INTENT_CONFIRMED, RPA_PENDING_APPROVAL, RPA_EXECUTING, WECHAT_ADD_REQUESTED
    failed: int = 0   # RPA_BLOCKED, RPA_FAILED, WECHAT_TARGET_NOT_FOUND, WECHAT_ADD_REJECTED, WECHAT_RISK_CONTROL, WECHAT_ACCEPTANCE_EXHAUSTED
    neutral: int = 0  # NEW_LEAD, RPA_SIMULATED
    status_counts: dict[str, int] = Field(default_factory=dict)  # Raw counts per individual status
