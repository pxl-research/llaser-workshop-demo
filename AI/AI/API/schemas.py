from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryRequest(StrictModel):
    question: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = Field(
        default=None,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )


class QueryResponse(BaseModel):
    answer: str


class LlmUpdateRequest(StrictModel):
    llm: str = Field(..., min_length=1, max_length=256)


class ReadinessComponentResponse(BaseModel):
    state: str
    model: Optional[str] = None


class ReadinessResponse(BaseModel):
    status: str
    components: dict[str, ReadinessComponentResponse]
    message: Optional[str] = None


class AlertActionRequest(StrictModel):
    action: Literal["accept", "deny"]


class SecurityConfigResponse(BaseModel):
    use_homebrew: bool
    use_nlp_defense: bool
    homebrew_status: str
    nlp_defense_status: str
    homebrew_error: Optional[str] = None
    homebrew_backend: Optional[Literal["spark", "openrouter"]] = None
    nlp_defense_error: Optional[str] = None
    nlp_confidence_threshold: float


class SecurityConfigUpdateRequest(BaseModel):
    use_homebrew: Optional[bool] = None
    use_nlp_defense: Optional[bool] = None
    nlp_confidence_threshold: Optional[float] = Field(default=None, ge=0.1, le=0.99)


class SystemPromptResponse(BaseModel):
    prompt: str
    default_prompt: str


class SystemPromptUpdateRequest(StrictModel):
    prompt: Optional[str] = None
