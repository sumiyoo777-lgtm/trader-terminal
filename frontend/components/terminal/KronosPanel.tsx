"use client";
// Kronos Forecast panel: forecast meta, the Kronos-Guided Kalman Filter
// stats + trust slider, Respect Score sub-scores, deviation, status banner.
import type { KronosView } from "@/lib/types";
import { fmt, label, tone } from "@/lib/format";
import { Badge, Card, EmptyState, Tooltip, cn } from "@/components/ui";

const STATUS_TONE: Record<string, string> = {
  strong_respect: "border-emerald-500/50 bg-emerald-500/10 text-emerald-300",
  moderate_respect: "border-lime-500/50 bg-lime-500/10 text-lime-300",
  mixed: "border-amber-500/50 bg-amber-500/10 text-amber-300",
  weak_respect: "border-orange-500/50 bg-orange-500/10 text-orange-300",
  failing_forecast: "border-red-500/60 bg-red-500/15 text-red-300",
  inverted_fade_warning: "border-red-500/60 bg-red-500/15 text-red-300",
};

function SubScore({
  name, value, max, tooltip,
}: { name: string; value: number; max: number; tooltip: string }) {
  const frac = Math.max(0, Math.min(1, value / max));
  return (
    <Tooltip text={tooltip} wide>
      <div className="flex w-full flex-col gap-1">
        <div className="flex justify-between text-[10px] text-zinc-400">
          <span>{name}</span>
          <span className="font-mono">{value.toFixed(1)}/{max}</span>
        </div>
        <div className="h-1.5 w-full rounded bg-zinc-800">
          <div
            className={cn("h-1.5 rounded", frac >= 0.7 ? "bg-emerald-500" : frac >= 0.4 ? "bg-amber-500" : "bg-red-500")}
            style={{ width: `${frac * 100}%` }}
          />
        </div>
      </div>
    </Tooltip>
  );
}

function Stat({ name, value, tooltip }: { name: string; value: string; tooltip?: string }) {
  const inner = (
    <div className="flex flex-col rounded border border-zinc-800/80 bg-zinc-950/40 px-2 py-1">
      <span className="text-[9px] uppercase tracking-wider text-zinc-500">{name}</span>
      <span className="font-mono text-xs text-zinc-200">{value}</span>
    </div>
  );
  return tooltip ? <Tooltip text={tooltip}>{inner}</Tooltip> : inner;
}

export function KronosPanel({
  view,
  slider,
  onSliderChange,
}: {
  view: KronosView | null;
  slider: number;
  onSliderChange: (v: number) => void;
}) {
  if (!view) {
    return (
      <Card title="Kronos forecast — Kronos-Guided Kalman Filter">
        <EmptyState>Loading Kronos state…</EmptyState>
      </Card>
    );
  }

  if (view.status !== "ok") {
    return (
      <Card title="Kronos forecast — Kronos-Guided Kalman Filter">
        <div className="flex flex-col gap-2">
          <Badge className="w-fit border-zinc-600 bg-zinc-800 text-zinc-300">Kronos unavailable</Badge>
          <p className="text-xs text-zinc-400">{view.message}</p>
          {view.availability && (
            <p className="text-[11px] text-zinc-500">
              Local runner: {view.availability.local_runner_available ? "available" : view.availability.reason}
              {" · "}manual import always available (bottom panel → Kronos).
            </p>
          )}
          <p className="text-[11px] text-zinc-500">
            The rest of the terminal (GEX, COT, news, regime) keeps working without Kronos.
          </p>
        </div>
      </Card>
    );
  }

  const f = view.forecast!;
  const k = view.kalman!;
  const r = view.respect!;
  const dev = view.deviation!;

  return (
    <Card
      title="Kronos forecast — Kronos-Guided Kalman Filter"
      right={
        <Badge className={STATUS_TONE[r.forecast_status] ?? "border-zinc-600"}>
          {label.forecastStatus(r.forecast_status)}
        </Badge>
      }
    >
      <div className="grid gap-4 lg:grid-cols-3">
        {/* forecast meta */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <span className={cn("font-mono text-xl font-bold", tone.direction(f.direction))}>
              {f.direction}
            </span>
            <span className="text-xs text-zinc-400">
              1H forecast · conf {fmt.num(f.confidence, 0)}
            </span>
            {view.daily_direction && (
              <Tooltip text="Latest daily Kronos forecast direction">
                <span className={cn("text-xs font-semibold", tone.direction(view.daily_direction))}>
                  1D {view.daily_direction}
                </span>
              </Tooltip>
            )}
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            <Stat name="Forecast start" value={fmt.nyDateTime(f.forecast_start_ny)} />
            <Stat name="Forecast end" value={fmt.nyDateTime(f.forecast_end_ny)} />
            <Stat name="Generated" value={fmt.nyDateTime(f.generated_at_ny)} />
            <Stat name="Model" value={`${f.model_version ?? "?"} (${f.source})`} />
            <Stat
              name="Band width avg"
              value={f.band_width_avg != null ? `${fmt.num(f.band_width_avg)} pts` : "no bands"}
              tooltip="Average distance between the upper and lower forecast band (treated as ±2σ by the Kalman filter)."
            />
            <Stat
              name="Deviation now"
              value={`${fmt.signed(dev.points, 1)} pts · ${fmt.pct(dev.percent)}`}
              tooltip="Live price minus the Kronos forecast value at the most recent realized step."
            />
          </div>
          <p className="text-[11px] italic text-zinc-500">
            Is the market following Kronos or breaking away from it? Kronos is the intended path,
            not a promise.
          </p>
        </div>

        {/* Kalman filter */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <Tooltip
              wide
              text="Slider maps to the Kalman Q/R ratio. 0 = trust the Kronos forecast (estimate hugs the path, slow to abandon it). 100 = trust live price (reactive, fastest failure detection). Steady-state gain = ratio/(1+ratio)."
            >
              <span className="text-[11px] font-semibold text-zinc-300">
                Kronos Trust / Kalman Reactivity
              </span>
            </Tooltip>
            <span className="font-mono text-xs text-zinc-400">{slider}</span>
          </div>
          <input
            type="range" min={0} max={100} value={slider}
            onChange={(e) => onSliderChange(Number(e.target.value))}
            className="w-full accent-violet-400"
          />
          <div className="flex justify-between text-[9px] uppercase tracking-wide text-zinc-600">
            <span>trust Kronos</span><span>balanced</span><span>trust live price</span>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            <Stat name="Tracking error" value={`${fmt.num(k.tracking_error)} pts`}
              tooltip="RMSE of (live price − Kronos forecast) over realized steps." />
            <Stat name="Mean |z|" value={fmt.num(k.mean_abs_z, 2)}
              tooltip="Average residual z-score (residual ÷ forecast σ). Above ~2.5 persistently = failing." />
            <Stat name="Direction agreement" value={k.direction_agreement != null ? `${Math.round(k.direction_agreement * 100)}%` : "—"}
              tooltip="Blend of per-step movement agreement with the forecast and net-direction match." />
            <Stat name="Band respect" value={k.band_respect_fraction != null ? `${Math.round(k.band_respect_fraction * 100)}%` : "—"}
              tooltip="Fraction of realized observations inside the forecast band (|z| ≤ 2)." />
          </div>
          {(k.failure_warning || k.inverted) && (
            <div className="rounded border border-red-600/50 bg-red-950/40 px-2 py-1.5 text-[11px] font-semibold text-red-300">
              {k.inverted
                ? "⚠ INVERTED: the market is moving persistently opposite to Kronos — fade warning."
                : "⚠ FORECAST FAILING: price has persistently breached the forecast band."}
            </div>
          )}
        </div>

        {/* respect score */}
        <div className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between">
            <Tooltip
              wide
              text="Transparent composite, total 100: direction (25) + path correlation (25) + band respect (20) + Kalman residual (20) + invalidation (10). Hover each bar for its formula."
            >
              <span className="text-[11px] font-semibold text-zinc-300">Kronos Respect Score</span>
            </Tooltip>
            <span className={cn("font-mono text-2xl font-bold", tone.score(r.score))}>
              {Math.round(r.score)}
            </span>
          </div>
          <span className="text-[10px] uppercase tracking-wide text-zinc-500">{label.respect(r.label)}</span>
          <SubScore name="Direction agreement" value={r.direction_score} max={25}
            tooltip={r.explanation.direction ?? ""} />
          <SubScore name="Path correlation" value={r.correlation_score} max={25}
            tooltip={r.explanation.correlation ?? ""} />
          <SubScore name="Band respect" value={r.band_respect_score} max={20}
            tooltip={r.explanation.band_respect ?? ""} />
          <SubScore name="Kalman residual" value={r.kalman_residual_score} max={20}
            tooltip={r.explanation.kalman_residual ?? ""} />
          <SubScore name="Invalidations" value={r.invalidation_score} max={10}
            tooltip={`${r.explanation.invalidation ?? ""} (count: ${r.invalidation_count})`} />
        </div>
      </div>
    </Card>
  );
}
