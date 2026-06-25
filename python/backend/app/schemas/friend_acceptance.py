from pydantic import BaseModel, Field


class FriendAcceptanceCheckRequest(BaseModel):
    lead_id: str = Field(min_length=1)


class FriendAcceptanceCheckResponse(BaseModel):
    lead_id: str | None = None
    phone_masked: str | None = None
    accepted: bool
    state: str | None = None
    matched_text: str | None = None
    screenshot_path: str | None = None
    steps: list[str] = Field(default_factory=list)
    checked_at: str


class FriendAcceptancePendingRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


class FriendAcceptanceBatchResponse(BaseModel):
    checked: int
    accepted: int
    results: list[FriendAcceptanceCheckResponse]
