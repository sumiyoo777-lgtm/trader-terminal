"""Application settings, loaded from environment / backend/.env.

Every operational knob the spec calls "configurable" lives here so nothing
is hardcoded in services or jobs.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./terminal.db"
    redis_url: str = ""

    flashalpha_api_key: str = ""
    flashalpha_base_url: str = "https://lab.flashalpha.com"
    news_api_key: str = ""
    market_data_api_key: str = ""

    kronos_model_path: str = ""
    kronos_device: str = "cpu"

    default_symbol: str = "MES"
    market_data_ticker: str = "MES=F"

    gex_primary_symbol: str = "SPX"
    gex_secondary_symbol: str = "SPY"
    gex_schedule: str = "09:35,10:30,11:30,13:30,15:30"

    app_timezone: str = "America/New_York"

    enable_local_kronos: bool = False
    enable_news_scoring: bool = True
    enable_gex_jobs: bool = True
    enable_cot_jobs: bool = True
    enable_scheduler: bool = True

    news_refresh_minutes: int = 10
    kalman_slider_default: int = 50

    demo_seed: bool = False

    # --- COT (CFTC public Socrata API; no key required) -------------------
    # TFF futures-only dataset and Legacy futures-only dataset ids.
    cot_tff_dataset: str = "gpe5-46if"
    cot_legacy_dataset: str = "6dca-aqww"
    # E-MINI S&P 500 (CME) contract market code; MES macro proxy per spec.
    cot_market_codes: str = "13874A"
    cot_market_name_like: str = "E-MINI S&P 500"
    cot_lookback_weeks: int = 156

    # Self-computed GEX fallback (BS gamma x OI from the yfinance option
    # chain) when FlashAlpha can't serve data (tier/quota/outage).
    enable_self_computed_gex: bool = True

    # --- GEX regime knobs --------------------------------------------------
    # "near gamma flip" when |spot - flip| / spot is under this percent
    gex_near_flip_pct: float = 0.35
    # wall "approach" alert distance, percent of spot
    gex_wall_approach_pct: float = 0.25
    gex_stale_minutes: int = 180

    # --- Kalman / respect knobs --------------------------------------------
    # residual z-score that counts as a band/forecast violation
    kalman_fail_z: float = 2.5
    # consecutive violating observations before "forecast failing"
    kalman_fail_persistence: int = 3
    # default 1-sigma forecast uncertainty as a fraction of price when a
    # forecast has no bands (0.0015 = 0.15%)
    kalman_default_sigma_pct: float = 0.0015

    # --- News knobs ---------------------------------------------------------
    news_cache_minutes: int = 5
    news_max_age_hours: int = 24

    @property
    def gex_schedule_list(self) -> list[str]:
        return [s.strip() for s in self.gex_schedule.split(",") if s.strip()]

    @property
    def cot_market_code_list(self) -> list[str]:
        return [s.strip() for s in self.cot_market_codes.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
