#!/usr/bin/env python3
"""Inner Kronos inference script for the trader terminal — runs inside the
Kronos skill's venv (~/.claude/skills/kronos/.venv, which has torch +
transformers + yfinance and the model repo cloned at .../kronos/_kronos).

Unlike kronos_forward_test's inner script (which emits summary fields only),
this one emits the FULL forecast path plus ensemble bands — the raw material
the Kronos-guided Kalman filter and Respect Score need.

Prints exactly one JSON object to stdout:
  {
    "symbol": ticker, "horizon": "hourly"|"daily",
    "generated_at": iso_utc, "current_price": float,
    "path":       [[iso_utc, mean_close], ...],
    "band_upper": [[iso_utc, ensemble_max_high], ...],
    "band_lower": [[iso_utc, ensemble_min_low], ...],
    "direction": "UP"|"DOWN"|"NEUTRAL",
    "confidence": float 0-100,
    "model_version": "NeoQuasar/Kronos-small"
  }
All progress goes to stderr so stdout stays parseable.

Usage: _kronos_path_inner.py <TICKER> <hourly|daily> [pred_len] [ensemble]
"""
from __future__ import annotations

import json
import os
import sys
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd

KRONOS_REPO = Path(os.environ.get("KRONOS_REPO", Path.home() / ".claude" / "skills" / "kronos" / "_kronos"))
sys.path.insert(0, str(KRONOS_REPO))

import yfinance as yf  # noqa: E402

try:
    from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: E402
except Exception as exc:  # environment problem, not logic
    print(f"ERROR loading Kronos model module: {exc}", file=sys.stderr)
    print(f"Expected Kronos repo at: {KRONOS_REPO}", file=sys.stderr)
    sys.exit(2)

TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-base"
MODEL_ID = "NeoQuasar/Kronos-small"
DEVICE = os.environ.get("KRONOS_DEVICE", "cpu")

HORIZONS = {
    # horizon: (yf interval, history period, default pred_len, step timedelta)
    "hourly": ("1h", "60d", 7, pd.Timedelta(hours=1)),
    "daily": ("1d", "720d", 5, pd.Timedelta(days=1)),
}
UP_DOWN_THRESHOLD_PCT = 0.25


def fetch_history(ticker: str, interval: str, period: str) -> pd.DataFrame:
    print(f"[kronos_path] fetching {ticker} {interval} history ({period})...", file=sys.stderr)
    data = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    if data.empty:
        raise SystemExit(f"No {interval} data returned for {ticker}")
    hist = data[["Open", "High", "Low", "Close", "Volume"]].copy()
    hist.columns = ["open", "high", "low", "close", "volume"]
    # keep tz so output timestamps can be emitted as true UTC
    if hist.index.tz is None:
        hist.index = hist.index.tz_localize("America/New_York")
    return hist.tail(500)


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: _kronos_path_inner.py <TICKER> <hourly|daily> [pred_len] [ensemble]", file=sys.stderr)
        return 1
    ticker = sys.argv[1]
    horizon = sys.argv[2].lower()
    if horizon not in HORIZONS:
        print(f"horizon must be hourly|daily, got {horizon}", file=sys.stderr)
        return 1
    interval, period, default_len, step = HORIZONS[horizon]
    pred_len = int(sys.argv[3]) if len(sys.argv) > 3 else default_len
    ensemble_size = int(sys.argv[4]) if len(sys.argv) > 4 else 3

    history = fetch_history(ticker, interval, period)
    last_ts = history.index[-1]
    current_price = float(history["close"].iloc[-1])

    print(f"[kronos_path] loading {MODEL_ID} ({DEVICE}, max_context=512)...", file=sys.stderr)
    tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_ID)
    model = Kronos.from_pretrained(MODEL_ID)
    predictor = KronosPredictor(model, tokenizer, device=DEVICE, max_context=512)

    model_input = history.copy()
    model_input.index = model_input.index.tz_localize(None)
    x_timestamp = pd.Series(model_input.index)
    future_naive = pd.DatetimeIndex([model_input.index[-1] + step * (i + 1) for i in range(pred_len)])
    y_timestamp = pd.Series(future_naive)

    paths = []
    for i in range(ensemble_size):
        print(f"[kronos_path] forecast pass {i + 1}/{ensemble_size}...", file=sys.stderr)
        forecast = predictor.predict(
            df=model_input, x_timestamp=x_timestamp, y_timestamp=y_timestamp,
            pred_len=pred_len, T=1.0, top_p=0.9, sample_count=1, verbose=False,
        )
        paths.append(forecast)

    mean_close = np.mean([p["close"].values for p in paths], axis=0)
    upper = np.max([p["high"].values for p in paths], axis=0)
    lower = np.min([p["low"].values for p in paths], axis=0)

    future_utc = [
        (last_ts + step * (i + 1)).tz_convert("UTC") if last_ts.tzinfo else
        (last_ts + step * (i + 1)).tz_localize(timezone.utc)
        for i in range(pred_len)
    ]
    iso = [t.isoformat().replace("+00:00", "Z") for t in future_utc]

    pct_change = (float(mean_close[-1]) - current_price) / current_price * 100.0
    if pct_change > UP_DOWN_THRESHOLD_PCT:
        direction = "UP"
    elif pct_change < -UP_DOWN_THRESHOLD_PCT:
        direction = "DOWN"
    else:
        direction = "NEUTRAL"

    # Confidence: tight ensemble agreement + narrow predicted range -> high.
    end_closes = [float(p["close"].iloc[-1]) for p in paths]
    spread_pct = (max(end_closes) - min(end_closes)) / current_price * 100.0
    range_pct = float(np.mean([
        (float(p["high"].max()) - float(p["low"].min())) / current_price * 100.0 for p in paths
    ]))
    confidence = round(float(np.clip(100.0 - spread_pct * 8.0 - range_pct * 3.0, 30.0, 95.0)), 1)

    generated_at = pd.Timestamp.now(tz="UTC").isoformat().replace("+00:00", "Z")
    print(json.dumps({
        "symbol": ticker,
        "horizon": horizon,
        "generated_at": generated_at,
        "current_price": round(current_price, 2),
        "path": [[t, round(float(v), 2)] for t, v in zip(iso, mean_close)],
        "band_upper": [[t, round(float(v), 2)] for t, v in zip(iso, upper)],
        "band_lower": [[t, round(float(v), 2)] for t, v in zip(iso, lower)],
        "direction": direction,
        "confidence": confidence,
        "model_version": MODEL_ID,
        "metadata": {
            "ensemble_size": ensemble_size,
            "pred_len": pred_len,
            "ensemble_spread_pct": round(spread_pct, 3),
            "mean_range_pct": round(range_pct, 3),
            "confidence_formula": "clip(100 - spread%*8 - range%*3, 30, 95)",
        },
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
