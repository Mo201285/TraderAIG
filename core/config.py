"""Central configuration management for TraderAIG.

Loads settings from environment variables with sensible defaults.
All system components import from here to avoid scattered config.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _resolve_log_dir() -> Path:
    raw = os.getenv("LOG_DIR", "logs")
    p = Path(raw)
    return p if p.is_absolute() else (ROOT_DIR / p)


def _resolve_terminal_path() -> str:
    raw = os.getenv("MT5_TERMINAL_PATH", "").strip()
    if raw:
        return raw
    for terminal in ("mt5-dev", "mt5-portable"):
        candidate = ROOT_DIR / terminal / "terminal64.exe"
        if candidate.is_file():
            return str(candidate)
    return ""


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: str

    @property
    def url(self) -> str:
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


@dataclass(frozen=True)
class RedisConfig:
    host: str
    port: int
    db: int

    @property
    def url(self) -> str:
        return f"redis://{self.host}:{self.port}/{self.db}"


@dataclass(frozen=True)
class MT5Config:
    login: int
    password: str
    server: str
    terminal_path: str
    symbols: str


@dataclass(frozen=True)
class CexConfig:
    """CEX Gateway activation + venue credentials.

    The gateway is paper-first by design: `mode` defaults to "paper", the
    live gate defaults to OFF, and no venue may open real positions unless
    `live_allowed` is explicitly enabled AND that venue's keys are present.
    Testnet keys are optional; without them the venue stays in observer mode.
    """
    mode: str                 # paper | testnet | live
    live_allowed: bool        # hard gate; real money stays off unless true
    venue: str                # binance | okx | bybit
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet_key: str = ""
    binance_testnet_secret: str = ""
    okx_api_key: str = ""
    okx_api_secret: str = ""
    okx_passphrase: str = ""
    okx_broker_id: str = ""
    okx_demo_api_key: str = ""
    okx_demo_api_secret: str = ""
    okx_demo_passphrase: str = ""
    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    bybit_testnet_key: str = ""
    bybit_testnet_secret: str = ""


@dataclass(frozen=True)
class PaymentsConfig:
    """Billing & wallet activation.

    Sandbox-first by design: `mode` defaults to "sandbox" and the live gate
    defaults to OFF. A real provider (stripe) may only move money when
    `live_allowed` is explicitly enabled AND the provider's key is present;
    otherwise it stays a locked observer (exactly the CEX discipline).
    """
    mode: str                 # sandbox | live
    live_allowed: bool        # hard gate; real money stays off unless true
    provider: str             # sandbox | stripe | pi
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    pi_api_key: str = ""
    pi_wallet_key: str = ""


@dataclass(frozen=True)
class APIConfig:
    host: str
    port: int


@dataclass(frozen=True)
class RiskDefaults:
    max_risk_per_trade: float
    max_daily_loss: float
    max_drawdown: float
    max_open_positions: int
    max_leverage: float
    require_stop_loss: bool


@dataclass(frozen=True)
class LoggingConfig:
    level: str
    directory: Path


@dataclass(frozen=True)
class Settings:
    database: DatabaseConfig
    redis: RedisConfig
    mt5: MT5Config
    cex: CexConfig
    payments: PaymentsConfig
    api: APIConfig
    risk_defaults: RiskDefaults
    logging: LoggingConfig
    root_dir: Path = ROOT_DIR

    @property
    def log_file(self) -> Path:
        return self.logging.directory / "system.log"


def load_settings() -> Settings:
    """Build settings from environment variables."""
    return Settings(
        database=DatabaseConfig(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=_env_int("POSTGRES_PORT", 5432),
            name=os.getenv("POSTGRES_DB", "traderaig"),
            user=os.getenv("POSTGRES_USER", "traderaig"),
            password=os.getenv("POSTGRES_PASSWORD", "change-me"),
        ),
        redis=RedisConfig(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=_env_int("REDIS_PORT", 6379),
            db=_env_int("REDIS_DB", 0),
        ),
        mt5=MT5Config(
            login=_env_int("MT5_LOGIN", 0),
            password=os.getenv("MT5_PASSWORD", ""),
            server=os.getenv("MT5_SERVER", ""),
            terminal_path=_resolve_terminal_path(),
            symbols=os.getenv("MT5_SYMBOLS", "XAUUSD"),
        ),
        cex=CexConfig(
            mode=os.getenv("CEX_MODE", "paper").lower(),
            live_allowed=_env_bool("CEX_LIVE_ALLOWED", False),
            venue=os.getenv("CEX_VENUE", "binance").lower(),
            binance_api_key=os.getenv("CEX_BINANCE_API_KEY", ""),
            binance_api_secret=os.getenv("CEX_BINANCE_API_SECRET", ""),
            binance_testnet_key=os.getenv("CEX_BINANCE_TESTNET_KEY", ""),
            binance_testnet_secret=os.getenv("CEX_BINANCE_TESTNET_SECRET", ""),
            okx_api_key=os.getenv("CEX_OKX_API_KEY", ""),
            okx_api_secret=os.getenv("CEX_OKX_API_SECRET", ""),
            okx_passphrase=os.getenv("CEX_OKX_PASSPHRASE", ""),
            okx_broker_id=os.getenv("CEX_OKX_BROKER_ID", ""),
            okx_demo_api_key=os.getenv("CEX_OKX_DEMO_API_KEY", ""),
            okx_demo_api_secret=os.getenv("CEX_OKX_DEMO_API_SECRET", ""),
            okx_demo_passphrase=os.getenv("CEX_OKX_DEMO_PASSPHRASE", ""),
            bybit_api_key=os.getenv("CEX_BYBIT_API_KEY", ""),
            bybit_api_secret=os.getenv("CEX_BYBIT_API_SECRET", ""),
            bybit_testnet_key=os.getenv("CEX_BYBIT_TESTNET_KEY", ""),
            bybit_testnet_secret=os.getenv("CEX_BYBIT_TESTNET_SECRET", ""),
        ),
        payments=PaymentsConfig(
            mode=os.getenv("PAYMENTS_MODE", "sandbox").lower(),
            live_allowed=_env_bool("PAYMENTS_LIVE_ALLOWED", False),
            provider=os.getenv("PAYMENTS_PROVIDER", "sandbox").lower(),
            stripe_secret_key=os.getenv("PAYMENTS_STRIPE_SECRET_KEY", ""),
            stripe_webhook_secret=os.getenv("PAYMENTS_STRIPE_WEBHOOK_SECRET", ""),
            pi_api_key=os.getenv("PAYMENTS_PI_API_KEY", ""),
            pi_wallet_key=os.getenv("PAYMENTS_PI_WALLET_KEY", ""),
        ),
        api=APIConfig(
            host=os.getenv("API_HOST", "0.0.0.0"),
            port=_env_int("API_PORT", 8000),
        ),
        risk_defaults=RiskDefaults(
            max_risk_per_trade=_env_float("RISK_MAX_PER_TRADE", 0.01),
            max_daily_loss=_env_float("RISK_MAX_DAILY_LOSS", 0.03),
            max_drawdown=_env_float("RISK_MAX_DRAWDOWN", 0.10),
            max_open_positions=_env_int("RISK_MAX_OPEN_POSITIONS", 5),
            max_leverage=_env_float("RISK_MAX_LEVERAGE", 10.0),
            require_stop_loss=_env_bool("RISK_REQUIRE_STOP_LOSS", True),
        ),
        logging=LoggingConfig(
            level=os.getenv("LOG_LEVEL", "INFO").upper(),
            directory=_resolve_log_dir(),
        ),
    )


settings = load_settings()
