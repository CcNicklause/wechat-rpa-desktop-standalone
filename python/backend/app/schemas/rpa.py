from pydantic import BaseModel, Field


class PrecheckRequest(BaseModel):
    lead_id: str


class CheckItem(BaseModel):
    name: str
    passed: bool
    message: str


class PrecheckResponse(BaseModel):
    allowed: bool
    rpa_mode: str
    dry_run_default: bool
    checks: list[CheckItem]


class AddWechatRequest(BaseModel):
    lead_id: str
    greeting: str = Field(min_length=1, max_length=200)
    dry_run: bool = True
    human_approval: bool = False


class AddWechatResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobResponse(BaseModel):
    job_id: str
    lead_id: str
    status: str
    rpa_mode: str
    dry_run: bool
    steps: list[str]
    error_code: str | None = None
    error_message: str | None = None
    # 终态分类：business=正常业务结果（搜不到/已好友/被拒/风控）；
    # system=系统故障（崩溃/超时/驱动不可用）；success=正常完成；None=进行中
    outcome_type: str | None = None
