"""Alert condition engine — pure comparison of the previous terminal state
vs the new one. The service layer persists returned alerts and logs them to
the console; the transport is swappable (email later) because conditions and
delivery are fully separated.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TerminalState:
    """The fields alert conditions care about, snapshotted per evaluation."""
    price: float | None = None
    gamma_flip: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    gex_regime: str | None = None
    respect_score: float | None = None
    forecast_failing: bool = False
    forecast_inverted: bool = False
    news_score: float | None = None
    red_folder: bool = False
    bias: str | None = None
    environment: str | None = None


@dataclass
class AlertEvent:
    alert_type: str
    severity: str  # info | warn | critical
    title: str
    message: str
    metadata: dict = field(default_factory=dict)


def _crossed(prev_p: float | None, new_p: float | None, level: float | None) -> bool:
    if None in (prev_p, new_p, level):
        return False
    return (prev_p - level) * (new_p - level) < 0


def _near(price: float | None, level: float | None, pct: float) -> bool:
    if None in (price, level) or not price:
        return False
    return abs(price - level) / abs(price) * 100.0 <= pct


def check_alert_conditions(
    prev: TerminalState | None,
    new: TerminalState,
    wall_approach_pct: float = 0.25,
    news_spike_delta: float = 30.0,
) -> list[AlertEvent]:
    alerts: list[AlertEvent] = []
    p = prev or TerminalState()

    # GEX regime changed
    if p.gex_regime and new.gex_regime and p.gex_regime != new.gex_regime:
        alerts.append(AlertEvent(
            "gex_regime_changed", "warn", "GEX regime changed",
            f"GEX regime moved {p.gex_regime} -> {new.gex_regime}. Hedging dynamics have flipped.",
            {"from": p.gex_regime, "to": new.gex_regime},
        ))

    # price crossed gamma flip
    if _crossed(p.price, new.price, new.gamma_flip):
        alerts.append(AlertEvent(
            "price_crossed_gamma_flip", "warn", "Price crossed the gamma flip",
            f"Price moved through the gamma flip {new.gamma_flip} "
            f"({p.price} -> {new.price}). Expect instability around this level.",
            {"gamma_flip": new.gamma_flip, "from": p.price, "to": new.price},
        ))

    # wall approaches (fire on entering the zone, not every tick inside it)
    for wall_name, level in (("call_wall", new.call_wall), ("put_wall", new.put_wall)):
        if _near(new.price, level, wall_approach_pct) and not _near(p.price, level, wall_approach_pct):
            alerts.append(AlertEvent(
                f"price_approaching_{wall_name}", "info",
                f"Price approaching the {wall_name.replace('_', ' ')}",
                f"Price {new.price} is within {wall_approach_pct}% of the "
                f"{wall_name.replace('_', ' ')} at {level}.",
                {"wall": wall_name, "level": level, "price": new.price},
            ))

    # respect score threshold crossings
    for threshold, severity in ((60.0, "warn"), (40.0, "critical")):
        if (
            new.respect_score is not None
            and new.respect_score < threshold
            and (p.respect_score is None or p.respect_score >= threshold)
        ):
            alerts.append(AlertEvent(
                f"respect_below_{int(threshold)}", severity,
                f"Kronos Respect Score below {int(threshold)}",
                f"Respect Score fell to {new.respect_score:.0f} "
                f"(was {p.respect_score if p.respect_score is not None else 'n/a'}). "
                + ("Forecast reliability is breaking down." if threshold == 40 else
                   "The market is getting noisy versus the forecast."),
                {"score": new.respect_score, "threshold": threshold},
            ))

    if new.forecast_inverted and not p.forecast_inverted:
        alerts.append(AlertEvent(
            "kronos_forecast_inverted", "critical", "Kronos forecast inverted",
            "The market is moving persistently OPPOSITE to the Kronos path — fade warning.",
        ))
    if new.forecast_failing and not p.forecast_failing:
        alerts.append(AlertEvent(
            "kronos_forecast_failed", "critical", "Kronos forecast failing",
            "Price has persistently breached the Kronos forecast band — the forecast is failing.",
        ))

    # news spike
    if (
        new.news_score is not None and p.news_score is not None
        and abs(new.news_score - p.news_score) >= news_spike_delta
    ):
        alerts.append(AlertEvent(
            "news_risk_spike", "warn", "News risk score spiked",
            f"Live News Risk Score jumped {p.news_score:.0f} -> {new.news_score:.0f}.",
            {"from": p.news_score, "to": new.news_score},
        ))

    if new.red_folder and not p.red_folder:
        alerts.append(AlertEvent(
            "red_folder_detected", "critical", "Red Folder news detected",
            "High-impact macro/Fed event detected today — conditions may be abnormal.",
        ))

    # unified regime / bias transitions
    if p.environment and new.environment and p.environment != new.environment:
        alerts.append(AlertEvent(
            "regime_changed", "warn", "Unified regime changed",
            f"Environment moved {p.environment} -> {new.environment}.",
            {"from": p.environment, "to": new.environment},
        ))
    if p.bias != new.bias and new.bias in ("long", "short"):
        alerts.append(AlertEvent(
            "bias_actionable", "info", f"Bias became actionable: {new.bias}",
            f"Unified bias moved {p.bias or 'none'} -> {new.bias}.",
            {"from": p.bias, "to": new.bias},
        ))
    if p.bias != new.bias and new.bias == "no_trade":
        alerts.append(AlertEvent(
            "no_trade_triggered", "warn", "No-trade condition triggered",
            f"Unified bias moved {p.bias or 'none'} -> no_trade.",
            {"from": p.bias},
        ))

    return alerts
