from pydantic import BaseModel, Field, model_validator


class TargetInput(BaseModel):
    ip_address: str | None = Field(default=None, min_length=2, max_length=45)
    ip: str | None = Field(default=None, min_length=2, max_length=45)
    label: str | None = Field(default=None, max_length=120)
    start_enumeration: bool = False

    @model_validator(mode="after")
    def validate_ip_fields(self) -> "TargetInput":
        if not (self.ip_address or self.ip):
            raise ValueError("ip_address is required")
        return self


class LlmPromptRequest(BaseModel):
    ip_address: str | None = Field(default=None, min_length=7, max_length=45)
    target_id: str | None = Field(default=None, min_length=8, max_length=32)
    prompt: str = Field(min_length=1, max_length=4000)
    model: str = Field(default="auto", max_length=120)
    context_block_ids: list[str] = Field(default_factory=list)
    include_services: bool = True
    include_findings: bool = True
    include_observations: bool = True
    include_pending_actions: bool = True
    include_timeline: bool = False

    @model_validator(mode="after")
    def validate_target_fields(self) -> "LlmPromptRequest":
        if not (self.target_id or self.ip_address):
            raise ValueError("target_id or ip_address is required")
        return self


class ContextBlockInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=20000)
    kind: str = Field(default="notes", min_length=2, max_length=40)


class ActionDecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=600)


class ShellSessionInput(BaseModel):
    protocol: str = Field(default="ssh", pattern="^(ssh|telnet|nc)$")
    host: str | None = Field(default=None, min_length=2, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=512)
    label: str | None = Field(default=None, max_length=160)
    cols: int = Field(default=100, ge=20, le=300)
    rows: int = Field(default=32, ge=8, le=120)


class LlmSettingsInput(BaseModel):
    llm_provider: str = Field(default="ollama", pattern="^(ollama|openrouter)$")
    ollama_base_url: str | None = Field(default=None, max_length=300)
    openrouter_api_key: str | None = Field(default=None, max_length=300)
    openrouter_base_url: str | None = Field(default="https://openrouter.ai/api/v1", max_length=300)
    openrouter_referer: str | None = Field(default=None, max_length=400)
    openrouter_title: str | None = Field(default=None, max_length=200)
    ollama_tailscale_host: str | None = Field(default=None, max_length=120)
    ollama_timeout_seconds: float = Field(default=5.0, ge=1, le=180)
    default_model: str = Field(default="auto", max_length=120)
    temperature: float = Field(default=0.2, ge=0, le=2)
    num_ctx: int = Field(default=8192, ge=1024, le=65536)
    autoplan_enabled: bool = False
    autoplan_interval_seconds: int = Field(default=20, ge=5, le=3600)
    autoplan_max_actions_per_turn: int = Field(default=4, ge=1, le=10)
    autoplan_include_timeline: bool = True
    autoplan_include_execution_history: bool = True
    autoplan_prompt: str = Field(default="", max_length=4000)
    system_prompt: str | None = Field(default=None, max_length=8000)
    command_allowlist: list[str] | None = None
    autonomy_profile: str = Field(default="through_privesc", pattern="^(recon_only|through_foothold|through_privesc)$")
    autonomy_pause_on_credential: bool = True
    autonomy_pause_on_session: bool = True
    autonomy_pause_on_privesc: bool = True
    autonomy_max_noise: str = Field(default="high", pattern="^(safe|low|medium|high)$")


class AutonomyProfileInput(BaseModel):
    profile: str = Field(pattern="^(recon_only|through_foothold|through_privesc)$")
