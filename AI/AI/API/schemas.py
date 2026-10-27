from typing import List, Literal, Optional

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


class ConfigUpdateRequest(StrictModel):
    config_type: Literal["llm", "embedding", "reranker"]
    value: str = Field(..., min_length=1, max_length=256)


class SystemInfoResponse(BaseModel):
    system_type: str


class ReadinessComponentResponse(BaseModel):
    state: str
    model: Optional[str] = None
    message: Optional[str] = None


class ReadinessResponse(BaseModel):
    status: str
    components: dict[str, ReadinessComponentResponse]
    message: Optional[str] = None


class ModelInfo(BaseModel):
    name: str
    description: Optional[str] = None


class ConfigResponse(BaseModel):
    status: str
    message: str
    config_type: Optional[str] = None
    value: Optional[str] = None


class MaliciousPromptAlert(BaseModel):
    id: str
    prompt: str
    timestamp: str
    riskLevel: str
    threatTypes: List[str]
    userIP: Optional[str] = None
    sessionID: Optional[str] = None
    status: str


class AlertActionRequest(StrictModel):
    action: Literal["accept", "deny"]


class SecurityConfigResponse(BaseModel):
    use_homebrew: bool
    use_nlp_defense: bool
    static_code_analysis_verified: bool
    homebrew_status: str
    nlp_defense_status: str
    homebrew_error: Optional[str] = None
    nlp_defense_error: Optional[str] = None
    nlp_confidence_threshold: float
    max_upload_size_mb: float
    max_output_tokens: int
    provider_timeout_seconds: float


class SecurityConfigUpdateRequest(BaseModel):
    use_homebrew: Optional[bool] = None
    use_nlp_defense: Optional[bool] = None
    nlp_confidence_threshold: Optional[float] = Field(default=None, ge=0.1, le=0.99)
    max_upload_size_mb: Optional[float] = Field(default=None, gt=0, le=500)
    max_output_tokens: Optional[int] = Field(default=None, ge=64, le=32768)
    provider_timeout_seconds: Optional[float] = Field(default=None, ge=1, le=300)
