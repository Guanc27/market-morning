from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    fmp_api_key: str = ""
    backend_host: str = "127.0.0.1"
    backend_port: int = 8742
    database_path: str = "./data/market_morning.db"
    anthropic_model: str = "claude-opus-4-8"
    # Faster/cheaper model for picks, portfolio, synopsis, explore
    anthropic_model_fast: str = "claude-sonnet-5"
    # Optional faster model for morning brief (empty = anthropic_model / Opus)
    anthropic_model_brief: str = ""
    mock_mode: bool = False
    robinhood_mcp_url: str = "https://agent.robinhood.com/mcp/trading"
    robinhood_mcp_access_token: str = ""
    robinhood_sync_proxy_url: str = ""
    robinhood_account_number: str = ""
    robinhood_sync_cooldown_seconds: int = 300

    @property
    def db_path(self) -> Path:
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
