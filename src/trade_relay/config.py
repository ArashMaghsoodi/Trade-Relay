"""
Central configuration, loaded from environment variables / .env.

Every other module should receive its settings through this object (passed
in via constructor / dependency injection) rather than reading os.environ
directly, so the whole app stays testable and each component's dependencies
are explicit.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- master safety switch ---
    live_trading_enabled: bool = Field(default=False, alias="LIVE_TRADING_ENABLED")

    # --- Telethon ---
    telegram_api_id: int = Field(default=0, alias="TELEGRAM_API_ID")
    telegram_api_hash: str = Field(default="", alias="TELEGRAM_API_HASH")
    telethon_session_name: str = Field(default="trade_relay_session", alias="TELETHON_SESSION_NAME")
    vip_channel_id: str = Field(default="", alias="VIP_CHANNEL_ID")

    # --- control bot ---
    control_bot_token: str = Field(default="", alias="CONTROL_BOT_TOKEN")
    owner_telegram_id: int = Field(default=0, alias="OWNER_TELEGRAM_ID")

    # --- TooBit ---
    toobit_api_key: str = Field(default="", alias="TOOBIT_API_KEY")
    toobit_api_secret: str = Field(default="", alias="TOOBIT_API_SECRET")
    toobit_base_url: str = Field(default="https://api.toobit.com", alias="TOOBIT_BASE_URL")

    # --- AI parser ---
    ai_parser_enabled: bool = Field(default=False, alias="AI_PARSER_ENABLED")
    ai_provider_base_url: str = Field(default="", alias="AI_PROVIDER_BASE_URL")
    ai_provider_api_key: str = Field(default="", alias="AI_PROVIDER_API_KEY")
    ai_provider_model: str = Field(default="", alias="AI_PROVIDER_MODEL")

    # --- position sizing ---
    default_wallet_percent: float = Field(default=5.0, alias="DEFAULT_WALLET_PERCENT")
    min_wallet_percent: float = Field(default=4.0, alias="MIN_WALLET_PERCENT")
    max_wallet_percent: float = Field(default=8.0, alias="MAX_WALLET_PERCENT")
    default_leverage: int = Field(default=10, alias="DEFAULT_LEVERAGE")

    # --- risk thresholds ---
    max_signal_age_seconds: int = Field(default=180, alias="MAX_SIGNAL_AGE_SECONDS")
    max_sl_distance_pct: float = Field(default=15.0, alias="MAX_SL_DISTANCE_PCT")
    max_tp_distance_pct: float = Field(default=50.0, alias="MAX_TP_DISTANCE_PCT")
    min_parser_confidence: float = Field(default=0.75, alias="MIN_PARSER_CONFIDENCE")

    # --- database ---
    database_url: str = Field(default="sqlite:///./trade_relay.db", alias="DATABASE_URL")

    # --- logging ---
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    def clamp_wallet_percent(self, requested: float | None) -> float:
        """Apply the configured min/max clamp to a provider-specified wallet %,
        falling back to the configured default when none was specified."""
        pct = requested if requested is not None else self.default_wallet_percent
        return max(self.min_wallet_percent, min(self.max_wallet_percent, pct))


def load_settings() -> Settings:
    return Settings()
