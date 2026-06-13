"use client";
import type { Summary } from "@/lib/types";
import { fmt, tone } from "@/lib/format";
import { Badge, Button, Spinner, StatusDot, Tooltip, cn } from "@/components/ui";

const SESSION_LABEL: Record<string, string> = {
  premarket: "PREMARKET", rth: "RTH", after_hours: "AFTER-HOURS", closed: "CLOSED",
};

export function ControlBar({
  summary,
  loading,
  onRefreshAll,
  refreshing,
}: {
  summary: Summary | null;
  loading: boolean;
  onRefreshAll: () => void;
  refreshing: boolean;
}) {
  const price = summary?.last_price;
  const health = summary?.data_health ?? {};
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-zinc-800 bg-zinc-900/80 px-4 py-2.5">
      <div className="flex items-baseline gap-2">
        <span className="text-lg font-bold tracking-tight text-zinc-100">
          {summary?.symbol ?? "MES"}
        </span>
        <span className="text-[11px] text-zinc-500">
          GEX proxy: {summary?.proxy_symbols?.join(" → ") ?? "SPX → SPY"}
        </span>
      </div>

      <div className="flex items-baseline gap-2 font-mono">
        <span className="text-xl font-semibold text-zinc-100">
          {loading ? <Spinner /> : fmt.price(price?.price)}
        </span>
        {price?.timestamp_ny && (
          <Tooltip text={`Source: ${price.source ?? "?"} · as of ${fmt.nyDateTime(price.timestamp_ny)} ET`}>
            <span className="text-[11px] text-zinc-500">{fmt.ago(price.timestamp_ny)}</span>
          </Tooltip>
        )}
      </div>

      <Badge className={cn("border", tone.session(summary?.session_status))}>
        {SESSION_LABEL[summary?.session_status ?? ""] ?? "—"}
      </Badge>

      <span className="text-[11px] text-zinc-500">
        {summary?.session_date} · {fmt.nyTime(summary?.now_ny)} ET
      </span>

      <div className="ml-auto flex items-center gap-3">
        <Tooltip
          wide
          text={
            <span>
              Data health:{" "}
              {Object.entries(health)
                .map(([k, v]) => `${k}: ${v.ok ? "ok" : "missing/error"}`)
                .join(" · ") || "no data yet"}
            </span>
          }
        >
          <span className="flex items-center gap-1.5">
            {(["price", "kronos", "gex", "cot", "news"] as const).map((k) => (
              <span key={k} className="flex items-center gap-0.5">
                <StatusDot ok={health[k]?.ok ?? null} />
                <span className="text-[9px] uppercase text-zinc-500">{k}</span>
              </span>
            ))}
          </span>
        </Tooltip>
        <Button onClick={onRefreshAll} disabled={refreshing} title="Re-fetch every panel">
          {refreshing ? <Spinner /> : "Refresh all"}
        </Button>
      </div>
    </div>
  );
}
