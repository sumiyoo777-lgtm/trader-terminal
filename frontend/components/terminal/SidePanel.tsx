"use client";
// Right side panel: unified regime card with reasons / invalidations /
// "what would change my mind", live alerts, data health.
import type { AlertView, RegimeSnapshotView, Summary } from "@/lib/types";
import { fmt, label, tone } from "@/lib/format";
import { Badge, Button, Card, EmptyState, StatusDot, Tooltip, cn } from "@/components/ui";

function BulletList({ items, marker, markerClass }: {
  items: string[]; marker: string; markerClass: string;
}) {
  if (!items.length) return <EmptyState>none</EmptyState>;
  return (
    <ul className="flex flex-col gap-1">
      {items.map((item, i) => (
        <li key={i} className="flex gap-1.5 text-[11px] leading-snug text-zinc-300">
          <span className={cn("shrink-0 font-bold", markerClass)}>{marker}</span>
          {item}
        </li>
      ))}
    </ul>
  );
}

export function RegimeCard({ regime }: { regime: RegimeSnapshotView | null }) {
  if (!regime) {
    return (
      <Card title="Unified regime">
        <EmptyState>No regime evaluation yet — refresh any panel to trigger one.</EmptyState>
      </Card>
    );
  }
  return (
    <Card
      title="Unified regime"
      right={<span className="text-[10px] text-zinc-500">{fmt.ago(regime.timestamp_ny)}</span>}
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Badge className={cn("border px-2 py-1 text-sm", tone.bias(regime.bias))}>
            {label.bias(regime.bias)}
          </Badge>
          <Badge className="border-zinc-600/60 bg-zinc-800/60 px-2 py-1 text-sm text-zinc-200">
            {label.environment(regime.environment)}
          </Badge>
          <Tooltip wide text={
            <span>
              Confidence terms:
              <ul className="mt-1 list-disc pl-4">
                {regime.confidence_terms.map((t, i) => <li key={i}>{t}</li>)}
              </ul>
            </span>
          }>
            <span className={cn("ml-auto font-mono text-xl font-bold", tone.score(regime.confidence))}>
              {Math.round(regime.confidence)}
            </span>
          </Tooltip>
        </div>

        {regime.playbook && (
          <div className="rounded border border-zinc-700/60 bg-zinc-800/40 px-2.5 py-2 text-[11px] leading-snug text-zinc-200">
            <span className="mr-1 font-semibold uppercase tracking-wide text-zinc-400">Playbook:</span>
            {regime.playbook}
          </div>
        )}

        <div>
          <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Reasons</h4>
          <BulletList items={regime.reasons} marker="•" markerClass="text-sky-400" />
        </div>
        <div>
          <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Invalidations</h4>
          <BulletList items={regime.invalidations} marker="✕" markerClass="text-red-400" />
        </div>
        <div>
          <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            What would change my mind?
          </h4>
          <BulletList items={regime.what_would_change_my_mind} marker="?" markerClass="text-amber-400" />
        </div>
      </div>
    </Card>
  );
}

export function AlertsCard({
  alerts, onAcknowledge,
}: { alerts: AlertView[]; onAcknowledge: (id: number) => void }) {
  return (
    <Card title={`Alerts (${alerts.length})`}>
      {alerts.length === 0 ? (
        <EmptyState>No unacknowledged alerts.</EmptyState>
      ) : (
        <ul className="flex max-h-72 flex-col gap-1.5 overflow-y-auto pr-1">
          {alerts.map((a) => (
            <li key={a.id} className={cn("rounded border px-2 py-1.5", tone.severity(a.severity))}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-[11px] font-semibold">{a.title}</div>
                  <div className="text-[10px] opacity-90">{a.message}</div>
                  <div className="mt-0.5 text-[9px] opacity-60">
                    {fmt.nyDateTime(a.timestamp_ny)} ET · {a.alert_type}
                  </div>
                </div>
                <Button className="shrink-0" onClick={() => onAcknowledge(a.id)} title="Acknowledge">
                  ack
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function DataHealthCard({ summary }: { summary: Summary | null }) {
  const health = summary?.data_health ?? {};
  const rows: { key: string; name: string; detail: (h: Record<string, unknown>) => string }[] = [
    { key: "price", name: "Price (yfinance)", detail: (h) => String(h.source ?? "no data") },
    {
      key: "kronos", name: "Kronos",
      detail: (h) =>
        h.ok
          ? `1H ${fmt.ago(h.hourly_generated_ny as string)}${h.daily_generated_ny ? ` · 1D ${fmt.ago(h.daily_generated_ny as string)}` : ""}`
          : `no forecast — ${String((h.reason as string) ?? "import one")}`,
    },
    {
      key: "gex", name: "GEX (FlashAlpha)",
      detail: (h) =>
        h.ok
          ? `${fmt.num(h.age_minutes as number, 0)}m old${h.is_stale ? " — STALE" : ""}`
          : "no snapshot",
    },
    {
      key: "cot", name: "COT (CFTC)",
      detail: (h) => String((h.note as string) ?? (h.ok ? "ok" : "no report")),
    },
    {
      key: "news", name: "News",
      detail: (h) => (h.ok ? `scored ${fmt.ago(h.last_scored_ny as string)}` : "no items"),
    },
  ];
  return (
    <Card title="Data health">
      <ul className="flex flex-col gap-1.5">
        {rows.map(({ key, name, detail }) => {
          const h = health[key] ?? { ok: null as unknown as boolean };
          return (
            <li key={key} className="flex items-center gap-2 text-[11px]">
              <StatusDot ok={(h.ok as boolean) ?? null} />
              <span className="w-32 shrink-0 text-zinc-300">{name}</span>
              <span className={cn("truncate", h.ok ? "text-zinc-500" : "text-amber-400")}>
                {detail(h as Record<string, unknown>)}
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
