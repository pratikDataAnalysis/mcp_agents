from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    app_env: str = "local"
    app_log_level: str = "INFO"
    base_url: str = "http://localhost:8000"

    # Agent configuration
    agent_config_path: str = "./src/app/agents/agent_config.json"
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
    openai_stt_force_english: bool = True

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
