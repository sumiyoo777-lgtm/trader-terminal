// Display helpers: numbers, NY timestamps, and the terminal color language.
import type { Bias, Direction, Environment, GexRegimeLabel } from "./types";

export const fmt = {
  price: (v: number | null | undefined, digits = 2) =>
    v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }),
  num: (v: number | null | undefined, digits = 1) =>
    v == null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: digits }),
  signed: (v: number | null | undefined, digits = 1) =>
    v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(digits)}`,
  pct: (v: number | null | undefined, digits = 2) =>
    v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`,
  compact: (v: number | null | undefined) =>
    v == null
      ? "—"
      : Math.abs(v) >= 1e9
        ? `${(v / 1e9).toFixed(2)}B`
        : Math.abs(v) >= 1e6
          ? `${(v / 1e6).toFixed(1)}M`
          : v.toLocaleString("en-US", { maximumFractionDigits: 0 }),
  nyTime: (iso: string | null | undefined) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleTimeString("en-US", {
      timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false,
    });
  },
  nyDateTime: (iso: string | null | undefined) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleString("en-US", {
      timeZone: "America/New_York", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", hour12: false,
    });
  },
  ago: (iso: string | null | undefined) => {
    if (!iso) return "—";
    const mins = Math.max(0, (Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${Math.round(mins)}m ago`;
    if (mins < 60 * 36) return `${(mins / 60).toFixed(1)}h ago`;
    return `${Math.round(mins / 60 / 24)}d ago`;
  },
};

export const label = {
  bias: (b: Bias | null | undefined): string =>
    b == null ? "—" : { long: "LONG", short: "SHORT", neutral: "NEUTRAL", no_trade: "NO-TRADE" }[b],
  environment: (e: Environment | null | undefined): string =>
    e == null
      ? "—"
      : {
          continuation: "Continuation", consolidation: "Consolidation",
          mean_reversion: "Mean reversion", reversal_risk: "Reversal risk",
          event_risk: "Event risk", no_trade: "No-trade",
        }[e],
  respect: (s: string | null | undefined): string =>
    s == null
      ? "—"
      : {
          highly_respected: "Highly respected", respected_noisy: "Respected, noisy",
          mixed: "Mixed", weak_respect: "Weak respect",
          failing_or_inverted: "Failing / inverted",
        }[s] ?? s,
  forecastStatus: (s: string | null | undefined): string =>
    s == null
      ? "—"
      : {
          strong_respect: "Strong respect", moderate_respect: "Moderate respect",
          mixed: "Mixed", weak_respect: "Weak respect",
          failing_forecast: "FAILING FORECAST", inverted_fade_warning: "INVERTED — FADE WARNING",
          kronos_unavailable: "Kronos unavailable",
        }[s] ?? s,
};

// Tailwind class fragments per state — the terminal's color language.
export const tone = {
  bias: (b: Bias | null | undefined): string =>
    b === "long" ? "text-emerald-400 border-emerald-500/40 bg-emerald-500/10"
    : b === "short" ? "text-red-400 border-red-500/40 bg-red-500/10"
    : b === "no_trade" ? "text-amber-400 border-amber-500/40 bg-amber-500/10"
    : "text-zinc-300 border-zinc-600/50 bg-zinc-700/20",
  direction: (d: Direction | null | undefined): string =>
    d === "UP" ? "text-emerald-400" : d === "DOWN" ? "text-red-400" : "text-zinc-300",
  gex: (g: GexRegimeLabel | null | undefined): string =>
    g === "positive" ? "text-sky-400 border-sky-500/40 bg-sky-500/10"
    : g === "negative" ? "text-fuchsia-400 border-fuchsia-500/40 bg-fuchsia-500/10"
    : g === "near_flip" ? "text-amber-400 border-amber-500/40 bg-amber-500/10"
    : "text-zinc-400 border-zinc-600/50 bg-zinc-700/20",
  score: (v: number | null | undefined): string =>
    v == null ? "text-zinc-400"
    : v >= 80 ? "text-emerald-400" : v >= 60 ? "text-lime-400"
    : v >= 40 ? "text-amber-400" : v >= 20 ? "text-orange-400" : "text-red-400",
  signedScore: (v: number | null | undefined): string =>
    v == null ? "text-zinc-400" : v > 15 ? "text-emerald-400" : v < -15 ? "text-red-400" : "text-zinc-300",
  severity: (s: "info" | "warn" | "critical"): string =>
    s === "critical" ? "border-red-500/50 bg-red-500/10 text-red-300"
    : s === "warn" ? "border-amber-500/50 bg-amber-500/10 text-amber-300"
    : "border-sky-500/40 bg-sky-500/10 text-sky-300",
  session: (s: string | null | undefined): string =>
    s === "rth" ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/40"
    : s === "premarket" || s === "after_hours" ? "bg-amber-500/15 text-amber-400 border-amber-500/40"
    : "bg-zinc-700/30 text-zinc-400 border-zinc-600/50",
};
