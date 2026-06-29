from datetime import datetime, timezone
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
    total: int
    by_status: dict[str, int]
    success: int
    running: int
    failure: int
    ts: str

    @classmethod
    def make(cls, by_status: dict[str, int]) -> "LeadStatsResponse":
        # 确保所有 15 个 LeadStatus 都存在，缺失补 0
        full_by_status: dict[str, int] = {status: by_status.get(status, 0) for status in LeadStatus}
        total = sum(full_by_status.values())
        success = full_by_status[LeadStatus.WECHAT_ACCEPTED]
        running = sum(full_by_status[s] for s in [
            LeadStatus.CALLING,
            LeadStatus.INTENT_CONFIRMED,
            LeadStatus.RPA_PENDING_APPROVAL,
            LeadStatus.RPA_SIMULATED,
            LeadStatus.RPA_EXECUTING,
            LeadStatus.WECHAT_ADD_REQUESTED,
        ])
        failure = sum(full_by_status[s] for s in [
            LeadStatus.RPA_FAILED,
            LeadStatus.RPA_BLOCKED,
            LeadStatus.WECHAT_RISK_CONTROL,
            LeadStatus.WECHAT_ADD_REJECTED,
            LeadStatus.WECHAT_TARGET_NOT_FOUND,
            LeadStatus.WECHAT_ACCEPTANCE_EXHAUSTED,
        ])
        ts = datetime.now(timezone.utc).isoformat()
        return cls(
            total=total,
            by_status=full_by_status,
            success=success,
            running=running,
            failure=failure,
            ts=ts,
        )
