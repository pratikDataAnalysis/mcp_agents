from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    app_env: str = "local"
    app_log_level: str = "INFO"
    base_url: str = "http://localhost:8000"

    # Agent configuration
    max_tools_per_agent: int = None

    # Twilio
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_from: str | None = None

    # Twilio – inbound webhook behavior
    twilio_validate_signature: bool = True

    # LLM
    llm_provider: str = "openai"
    openai_api_key: str | None = None
    llm_model_name: str | None = None
    openai_transcriptions_url: str = "https://api.openai.com/v1/audio/transcriptions"
    openai_translations_url: str = "https://api.openai.com/v1/audio/translations"
    openai_tts_url: str = "https://api.openai.com/v1/audio/speech"
    openai_stt_force_english: bool = True

    # Audio / TTS defaults
    # Default to the most compatible OpenAI TTS model name; can be overridden via .env
    tts_model_name: str = "tts-1"
    tts_voice: str = "alloy"
    tts_format: str = "mp3"

    # Outbound audio reply delivery (WhatsApp voice-note -> reply with text + audio)
    #
    # IMPORTANT: Twilio requires a publicly reachable HTTPS URL for media delivery.
    # In local dev, you typically set `MEDIA_PUBLIC_BASE_URL` to your ngrok URL.
    reply_with_audio_when_inbound_has_audio: bool = True
    media_root_dir: str = "./data/media"
    media_public_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("MEDIA_PUBLIC_BASE_URL", "media_public_base_url"),
    )

    # LangSmith / LangChain tracing (optional)
    # Prefer standard LANGCHAIN_* env vars; keep LANGSMITH_* as backwards-compatible aliases.
    langchain_tracing_v2: bool = Field(
        default=False,
        validation_alias=AliasChoices("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING"),
    )
    langchain_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY"),
    )
    langchain_project: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGCHAIN_PROJECT", "LANGSMITH_PROJECT"),
    )
    langchain_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGCHAIN_ENDPOINT", "LANGSMITH_ENDPOINT"),
    )

    # MCP (generic)
    mcp_config_path: str = "./mcp_configs/mcp_servers.json"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # Redis Streams
    redis_stream_inbound: str = "inbound_messages"
    redis_stream_outbound: str = "outbound_messages"

    # Redis Worker
    redis_consumer_group: str = "agent_workers"
    redis_consumer_name: str = "worker-1"
    worker_max_concurrency: int = 10

    # Outbound Dispatcher
    redis_outbound_consumer_group: str = "outbound_dispatchers"
    redis_outbound_consumer_name: str = "dispatcher-1"
    outbound_max_concurrency: int = 10
        
    # Idempotency
    outbound_idempotency_ttl_seconds: int = 7 * 24 * 60 * 60  # 7 days

    # Notes page id
    notes_parent_page_id: str | None = None


settings = Settings()
