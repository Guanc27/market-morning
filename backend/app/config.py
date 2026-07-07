from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    fmp_api_key: str = ""
    backend_host: str = "127.0.0.1"
    backend_port: int = 8742
    database_path: str = "./data/market_morning.db"
    # SaaS mode: hosted standalone app with auth + subscriptions (Mac app keeps saas_mode=false)
    saas_mode: bool = False
    jwt_secret: str = ""
    jwt_expire_days: int = 30
    auth_password_salt: str = "market-morning-dev-salt-change-in-production"
    session_cookie_name: str = "mm_session"
    web_app_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # Stripe (test mode price IDs from Dashboard)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_pro_monthly: str = ""
    stripe_price_pro_yearly: str = ""
    stripe_price_desk_monthly: str = ""
    stripe_price_desk_yearly: str = ""
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
