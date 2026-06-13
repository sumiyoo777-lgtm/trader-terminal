"use client";
import type { Summary } from "@/lib/types";
import { fmt, label, tone } from "@/lib/format";
import { Badge, Tooltip, cn } from "@/components/ui";
import { ReactNode } from "react";

function ScoreCard({
  name,
  value,
  sub,
  valueClass,
  tooltip,
}: {
  name: string;
  value: ReactNode;
  sub?: ReactNode;
  valueClass?: string;
  tooltip: ReactNode;
}) {
  return (
    <Tooltip text={tooltip} wide>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5 rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2">
        <span className="truncate text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          {name}
        </span>
        <span className={cn("truncate font-mono text-base font-bold leading-tight", valueClass ?? "text-zinc-200")}>
          {value}
        </span>
        {sub && <span className="truncate text-[10px] text-zinc-500">{sub}</span>}
      </div>
    </Tooltip>
  );
}

export function ScoreRow({ summary }: { summary: Summary | null }) {
  const s = summary?.scores;
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
      <ScoreCard
        name="Unified bias"
        value={label.bias(s?.bias)}
        sub={label.environment(s?.environment)}
        valueClass={tone.bias(s?.bias).split(" ")[0]}
        tooltip="Output of the unified regime engine: Kronos direction gated by Respect Score, then checked against GEX, COT, and news. See the regime card for the full reasoning."
      />
      <ScoreCard
        name="Confidence"
        value={s?.confidence != null ? `${Math.round(s.confidence)}` : "—"}
        sub="0–100"
        valueClass={tone.score(s?.confidence)}
        tooltip="Additive, fully disclosed formula: starts at 50, adjusted by respect, hourly/daily agreement, GEX alignment, news/COT alignment, red-folder and failure penalties. Every term is listed in the regime card."
      />
      <ScoreCard
        name="Kronos respect"
        value={s?.kronos_respect != null ? Math.round(s.kronos_respect) : "—"}
        sub="is price obeying Kronos?"
        valueClass={tone.score(s?.kronos_respect)}
        tooltip="0–100 composite: direction agreement (25) + path correlation (25) + band respect (20) + Kalman residual (20) + invalidations (10). 80+ highly respected · <20 failing/inverted. Sub-scores in the Kronos panel."
      />
      <ScoreCard
        name="Kronos 1H"
        value={s?.kronos_hourly_direction ?? "—"}
        valueClass={tone.direction(s?.kronos_hourly_direction)}
        tooltip="Latest hourly Kronos forecast direction (the 'intended path' of price)."
      />
      <ScoreCard
        name="Kronos 1D"
        value={s?.kronos_daily_direction ?? "—"}
        valueClass={tone.direction(s?.kronos_daily_direction)}
        tooltip="Latest daily Kronos forecast direction. Divergence from the hourly forecast reduces unified confidence."
      />
      <ScoreCard
        name="GEX regime"
        value={(s?.gex_regime ?? "unknown").replace("_", " ").toUpperCase()}
        sub={s?.gex_score != null ? `score ${fmt.signed(s.gex_score, 0)}` : undefined}
        valueClass={tone.gex(s?.gex_regime).split(" ")[0]}
        tooltip="Positive gamma → dealers dampen moves (mean reversion). Negative gamma → dealers amplify (momentum/expansion). Near flip → unstable. Score sign = regime type, NOT long/short bias."
      />
      <ScoreCard
        name="COT exposure"
        value={s?.cot_score != null ? fmt.signed(s.cot_score, 0) : "—"}
        sub={s?.cot_label?.replace(/_/g, " ")}
        valueClass={tone.signedScore(s?.cot_score)}
        tooltip="Weekly E-mini S&P 500 speculator positioning percentile, scaled to -100 (crowded short) … +100 (crowded long). Slow macro input — never intraday timing."
      />
      <ScoreCard
        name="News rating"
        value={
          <span className="flex items-center gap-1.5">
            {s?.news_score != null ? fmt.signed(s.news_score, 0) : "—"}
            {s?.red_folder && <Badge className="border-red-500/60 bg-red-500/15 text-red-300">RED FOLDER</Badge>}
          </span>
        }
        valueClass={tone.signedScore(s?.news_score)}
        tooltip="Live News Risk Score: relevance- and recency-weighted headline sentiment, -100 risk-off … +100 risk-on. RED FOLDER = high-impact macro/Fed event today; expect abnormal conditions. Overlay only, never a standalone signal."
      />
    </div>
  );
}
