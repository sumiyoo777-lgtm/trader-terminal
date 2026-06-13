"""Database models — one table per spec section, portable across
SQLite/PostgreSQL (no dialect-specific types; JSON stored as TEXT-backed
SQLAlchemy JSON). All timestamps are stored in UTC; the API layer converts
to America/New_York for display.
"""
from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class MarketPrice(Base):
    __tablename__ = "market_prices"
    __table_args__ = (Index("ix_market_prices_symbol_ts", "symbol", "timestamp", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="yfinance")


class KronosForecast(Base):
    __tablename__ = "kronos_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    horizon: Mapped[str] = mapped_column(String(8), index=True)  # "hourly" | "daily"
    generated_at: Mapped[datetime] = mapped_column(DateTime)  # UTC
    forecast_start: Mapped[datetime] = mapped_column(DateTime)  # UTC
    forecast_end: Mapped[datetime] = mapped_column(DateTime)  # UTC
    # path_json: [[iso_utc_timestamp, value], ...]
    path_json: Mapped[list] = mapped_column(JSON)
    direction: Mapped[str] = mapped_column(String(8))  # UP | DOWN | NEUTRAL | CHOP
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-100
    band_upper_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    band_lower_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="import")  # import | local_runner | demo
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class KronosRespectScore(Base):
    __tablename__ = "kronos_respect_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    session_date: Mapped[date] = mapped_column(Date, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    score: Mapped[float] = mapped_column(Float)
    direction_score: Mapped[float] = mapped_column(Float)
    correlation_score: Mapped[float] = mapped_column(Float)
    band_respect_score: Mapped[float] = mapped_column(Float)
    kalman_residual_score: Mapped[float] = mapped_column(Float)
    invalidation_score: Mapped[float] = mapped_column(Float)
    invalidation_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class GexSnapshot(Base):
    __tablename__ = "gex_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)  # symbol actually fetched (SPX/SPY)
    proxy_for: Mapped[str] = mapped_column(String(16))  # trading symbol this proxies (MES)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_gex: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_gex_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gamma_flip: Mapped[float | None] = mapped_column(Float, nullable=True)
    call_wall: Mapped[float | None] = mapped_column(Float, nullable=True)
    put_wall: Mapped[float | None] = mapped_column(Float, nullable=True)
    largest_positive_gex_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    largest_negative_gex_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    # status: ok | cached | partial | single_expiry | error | demo
    status: Mapped[str] = mapped_column(String(24), default="ok")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CotReport(Base):
    __tablename__ = "cot_reports"
    __table_args__ = (
        Index(
            "ix_cot_unique",
            "report_type", "market_code", "report_date", "participant_group",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_type: Mapped[str] = mapped_column(String(16))  # "legacy" | "tff"
    market_name: Mapped[str] = mapped_column(String(128))
    market_code: Mapped[str] = mapped_column(String(16), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    as_of_date: Mapped[date] = mapped_column(Date)
    participant_group: Mapped[str] = mapped_column(String(32))
    long_positions: Mapped[float | None] = mapped_column(Float, nullable=True)
    short_positions: Mapped[float | None] = mapped_column(Float, nullable=True)
    spreading: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_interest: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CotExposureScore(Base):
    __tablename__ = "cot_exposure_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_name: Mapped[str] = mapped_column(String(128))
    report_date: Mapped[date] = mapped_column(Date, index=True)
    score: Mapped[float] = mapped_column(Float)  # -100..+100
    net_position: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_percentile: Mapped[float | None] = mapped_column(Float, nullable=True)
    four_week_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    thirteen_week_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    crowding_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (Index("ix_news_url", "url", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC publish time
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(512))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment_score: Mapped[float] = mapped_column(Float)  # -1..+1
    volatility_score: Mapped[str] = mapped_column(String(8))  # low|medium|high
    relevance_score: Mapped[str] = mapped_column(String(8))  # low|medium|high
    urgency_score: Mapped[str] = mapped_column(String(8))  # low|medium|high
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class NewsRiskScore(Base):
    __tablename__ = "news_risk_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    score: Mapped[float] = mapped_column(Float)  # -100..+100
    red_folder_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class TerminalRegimeSnapshot(Base):
    __tablename__ = "terminal_regime_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    bias: Mapped[str] = mapped_column(String(16))
    environment: Mapped[str] = mapped_column(String(24))
    confidence: Mapped[float] = mapped_column(Float)
    kronos_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    gex_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cot_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    news_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    invalidations_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    alert_type: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[str] = mapped_column(String(8))  # info|warn|critical
    title: Mapped[str] = mapped_column(String(256))
    message: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
