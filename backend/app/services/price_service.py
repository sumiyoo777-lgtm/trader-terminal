"""Market price service — yfinance-backed (free, no key) hourly OHLCV for
the trading symbol (MES via MES=F), persisted to market_prices in UTC.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import MarketPrice
from ..time_utils import from_db, iso_ny, to_utc_naive, utc_now

log = logging.getLogger(__name__)


def refresh_prices(db: Session, settings: Settings, period: str = "10d") -> dict:
    """Pull hourly OHLCV and upsert new candles. Returns counts or error."""
    try:
        import yfinance as yf
    except ImportError:
        return {"ok": False, "error": "yfinance not installed"}

    ticker = settings.market_data_ticker
    try:
        raw = yf.Ticker(ticker).history(period=period, interval="1h", auto_adjust=False)
    except Exception as exc:
        log.warning("price fetch failed for %s: %s", ticker, exc)
        return {"ok": False, "error": f"yfinance fetch failed: {exc}"}
    if raw.empty:
        return {"ok": False, "error": f"no hourly data returned for {ticker}"}

    if raw.index.tz is None:
        raw.index = raw.index.tz_localize("America/New_York")
    raw.index = raw.index.tz_convert("UTC")

    existing = set(
        db.scalars(
            select(MarketPrice.timestamp).where(MarketPrice.symbol == settings.default_symbol)
        )
    )
    inserted = 0
    for ts, row in raw.iterrows():
        naive = ts.tz_localize(None).to_pydatetime()
        if naive in existing:
            continue
        db.add(
            MarketPrice(
                symbol=settings.default_symbol,
                timestamp=naive,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]) if row["Volume"] == row["Volume"] else None,
                source=f"yfinance:{ticker}",
            )
        )
        inserted += 1
    db.commit()
    return {"ok": True, "inserted": inserted, "ticker": ticker}


def latest_price(db: Session, settings: Settings) -> dict:
    """Live-ish last price: yfinance fast_info first, DB candle fallback.
    Always says where the number came from and how old it is."""
    price = None
    source = None
    ts = None
    try:
        import yfinance as yf

        info = yf.Ticker(settings.market_data_ticker).fast_info
        raw = info.get("lastPrice") if hasattr(info, "get") else getattr(info, "last_price", None)
        if raw is not None:
            price = float(raw)
            source = f"yfinance:fast_info:{settings.market_data_ticker}"
            ts = utc_now()
    except Exception as exc:
        log.debug("fast_info failed: %s", exc)

    if price is None:
        row = db.scalars(
            select(MarketPrice)
            .where(MarketPrice.symbol == settings.default_symbol)
            .order_by(MarketPrice.timestamp.desc())
            .limit(1)
        ).first()
        if row:
            price = row.close
            source = f"db_last_close ({row.source})"
            ts = from_db(row.timestamp)

    return {
        "symbol": settings.default_symbol,
        "price": price,
        "source": source,
        "timestamp_ny": iso_ny(ts) if ts else None,
        "age_seconds": None if ts is None else round((utc_now() - ts).total_seconds(), 1),
    }


def candles_between(
    db: Session, symbol: str, start_utc: datetime, end_utc: datetime
) -> list[MarketPrice]:
    return list(
        db.scalars(
            select(MarketPrice)
            .where(
                MarketPrice.symbol == symbol,
                MarketPrice.timestamp >= start_utc.replace(tzinfo=None),
                MarketPrice.timestamp <= end_utc.replace(tzinfo=None),
            )
            .order_by(MarketPrice.timestamp.asc())
        )
    )


def session_price_path(db: Session, settings: Settings, hours_back: int = 30) -> list[dict]:
    """Recent close path for the main chart."""
    start = utc_now() - timedelta(hours=hours_back)
    rows = candles_between(db, settings.default_symbol, start, utc_now())
    return [
        {"timestamp": row.timestamp.isoformat() + "Z", "close": row.close,
         "open": row.open, "high": row.high, "low": row.low, "volume": row.volume}
        for row in rows
    ]
