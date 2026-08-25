from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    telegram_api_id: str
    telegram_api_hash: str
    telegram_phone: str
    telegram_session_name: str
    vip_channel_ids: list[int]

    telegram_bot_token: str
    telegram_allowed_user_id: int

    toobit_api_key: str
    toobit_api_secret: str
    toobit_base_url: str
    toobit_futures_base_url: str

    trading_mode: str
    default_leverage: int
    max_leverage: int
    risk_per_trade_percent: float
    margin_mode: str
    one_position_per_symbol: bool
    log_level: str
    state_db_path: str

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Settings":
        load_dotenv(dotenv_path=env_file, override=False)

        def get(name: str, default: str | None = None) -> str:
            value = os.getenv(name, default)
            if value is None or value == "":
                raise ValueError(f"Missing required environment variable: {name}")
            return value

        raw_channels = os.getenv("VIP_CHANNEL_IDS", "").strip()
        channels = [int(x.strip()) for x in raw_channels.split(",") if x.strip()]

        trading_mode = os.getenv("TRADING_MODE", "dry_run").lower()
        allowed_modes = {"dry_run", "paper", "live"}
        if trading_mode not in allowed_modes:
            raise ValueError(f"TRADING_MODE must be one of {sorted(allowed_modes)}; got: {trading_mode}")

        return cls(
            telegram_api_id=get("TELEGRAM_API_ID"),
            telegram_api_hash=get("TELEGRAM_API_HASH"),
            telegram_phone=get("TELEGRAM_PHONE"),
            telegram_session_name=os.getenv("TELEGRAM_SESSION_NAME", "trade_relay"),
            vip_channel_ids=channels,
            telegram_bot_token=get("TELEGRAM_BOT_TOKEN"),
            telegram_allowed_user_id=int(get("TELEGRAM_ALLOWED_USER_ID")),
            toobit_api_key=os.getenv("TOOBIT_API_KEY", ""),
            toobit_api_secret=os.getenv("TOOBIT_API_SECRET", ""),
            toobit_base_url=os.getenv("TOOBIT_BASE_URL", "https://api.toobit.com"),
            toobit_futures_base_url=os.getenv("TOOBIT_FUTURES_BASE_URL", "https://fapi.toobit.com"),
            trading_mode=trading_mode,
            default_leverage=int(os.getenv("DEFAULT_LEVERAGE", "10")),
            max_leverage=int(os.getenv("MAX_LEVERAGE", "15")),
            risk_per_trade_percent=float(os.getenv("RISK_PER_TRADE_PERCENT", "1")),
            margin_mode=os.getenv("MARGIN_MODE", "cross").lower(),
            one_position_per_symbol=os.getenv("ONE_POSITION_PER_SYMBOL", "true").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            state_db_path=os.getenv("STATE_DB_PATH", "trade_relay.db"),
        )
