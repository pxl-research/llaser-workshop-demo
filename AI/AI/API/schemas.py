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
    # Set when a defense blocked the question and created an alert.
    alert_id: Optional[str] = None


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


class AlertStatusResponse(BaseModel):
    status: Literal["pending", "accepted", "denied"]


class AlertReleaseRequest(StrictModel):
    session_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


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


class RedteamRun(BaseModel):
    """One promptfoo red-team run, as the Red team page shows it."""

    id: str
    name: str
    # Milliseconds since 1970, as promptfoo stores it.
    created_at: int
    # "workshop" or "full"; None for runs not started with ./005_promptfoo_run.sh.
    attack_set: Optional[str] = None
    # The LLASER settings during the run (model, defenses, system prompt), from the run's tags.
    settings: dict[str, str]
    attacks: int
    got_through: int
    errors: int


class RedteamRunsResponse(BaseModel):
    runs: list[RedteamRun]
    # The browser opens the promptfoo UI on this port of the host it uses for LLASER.
    promptfoo_ui_port: int


class RedteamRunRequest(StrictModel):
    """Start a run from the Automated red teaming page."""

    # The same names ./005_promptfoo_run.sh and the runner accept; a letter or digit first,
    # so a name never looks like a command-line option.
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    attack_set: Literal["quick", "workshop", "full"] = "workshop"


class RedteamJob(BaseModel):
    """The run started from the page, while promptfoo runs it and after."""

    name: str
    attack_set: str
    status: Literal["running", "complete", "error"]
    # Attacks done so far, of total; total is 0 until promptfoo has loaded the attack set.
    progress: int
    total: int
    # The finished run in the run list.
    run_id: Optional[str] = None
    error: Optional[str] = None


class RedteamCurrentJobResponse(BaseModel):
    # None when no run was started from the page since the backend started.
    job: Optional[RedteamJob] = None
