"use client";
// Bottom tabbed tables: GEX snapshots, COT exposure, news items,
// Kronos forecast import/history, terminal regime history.
import { useState } from "react";
import type {
  CotView, GexView, KronosView, NewsView, RegimeView,
} from "@/lib/types";
import { api } from "@/lib/api";
import { fmt, label, tone } from "@/lib/format";
import { Badge, Button, Card, EmptyState, ErrorState, Spinner, Tooltip, cn } from "@/components/ui";

const TABS = ["GEX", "COT", "News", "Kronos", "Regime history"] as const;
type Tab = (typeof TABS)[number];

export function BottomPanels({
  gex, cot, news, kronos, regime, onChanged,
}: {
  gex: GexView | null;
  cot: CotView | null;
  news: NewsView | null;
  kronos: KronosView | null;
  regime: RegimeView | null;
  onChanged: () => void;
}) {
  const [tab, setTab] = useState<Tab>("GEX");
  return (
    <Card
      title={
        <span className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "rounded px-2 py-0.5 text-[11px] font-semibold transition-colors",
                tab === t ? "bg-zinc-700 text-zinc-100" : "text-zinc-500 hover:text-zinc-300",
              )}
            >
              {t}
            </button>
          ))}
        </span>
      }
    >
      {tab === "GEX" && <GexTable gex={gex} onChanged={onChanged} />}
      {tab === "COT" && <CotTable cot={cot} onChanged={onChanged} />}
      {tab === "News" && <NewsTable news={news} onChanged={onChanged} />}
      {tab === "Kronos" && <KronosTab kronos={kronos} onChanged={onChanged} />}
      {tab === "Regime history" && <RegimeHistory regime={regime} />}
    </Card>
  );
}

function Th({ children, tip }: { children: React.ReactNode; tip?: string }) {
  return (
    <th className="whitespace-nowrap px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
      {tip ? <Tooltip text={tip}>{children}</Tooltip> : children}
    </th>
  );
}
function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn("whitespace-nowrap px-2 py-1.5 font-mono text-[11px] text-zinc-300", className)}>{children}</td>;
}

// ---------------------------------------------------------------- GEX
function GexTable({ gex, onChanged }: { gex: GexView | null; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const refresh = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api.gexRefresh();
      if (!r.ok) setErr(`${r.kind}: ${r.message}`);
      onChanged();
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const rows = gex?.todays_snapshots ?? [];
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-zinc-400">
        <Button onClick={refresh} disabled={busy}>{busy ? <Spinner /> : "Fetch GEX now"}</Button>
        <span>Schedule (ET): {gex?.schedule_ny?.join(", ") ?? "—"}</span>
        {gex?.day_trend && <Badge>net GEX {gex.day_trend}</Badge>}
        {gex?.is_stale && <Badge className="border-amber-500/50 bg-amber-500/10 text-amber-300">
          STALE ({fmt.num(gex.age_minutes, 0)}m &gt; {gex.stale_threshold_minutes}m)
        </Badge>}
      </div>
      {err && <ErrorState>GEX refresh failed — {err}</ErrorState>}
      {gex?.latest_error && !rows.length && (
        <ErrorState>Last attempt: {gex.latest_error.error_message}</ErrorState>
      )}
      {rows.length === 0 ? (
        <EmptyState>No GEX snapshots today. FlashAlpha key required (FLASHALPHA_API_KEY).</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead><tr className="border-b border-zinc-800">
              <Th>Time ET</Th><Th>Sym</Th><Th tip="GEX is computed on the proxy; MES levels are approximate conversions">Proxy for</Th>
              <Th>Spot</Th><Th>Net GEX</Th><Th>Δ prev</Th><Th>γ-flip</Th><Th>Call wall</Th><Th>Put wall</Th>
              <Th tip="distance from spot to flip in proxy points">→flip</Th>
              <Th>→call</Th><Th>→put</Th><Th>Regime</Th><Th>Status</Th>
            </tr></thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className="border-b border-zinc-800/50">
                  <Td>{fmt.nyTime(s.timestamp_ny)}</Td>
                  <Td>{s.symbol}</Td>
                  <Td className="text-zinc-500">{s.proxy_for} (≈)</Td>
                  <Td>{fmt.price(s.underlying_price)}</Td>
                  <Td>{fmt.compact(s.net_gex)}</Td>
                  <Td>{s.net_gex_change != null ? fmt.compact(s.net_gex_change) : "—"}</Td>
                  <Td>{fmt.price(s.gamma_flip)}</Td>
                  <Td>{fmt.price(s.call_wall)}</Td>
                  <Td>{fmt.price(s.put_wall)}</Td>
                  <Td>{fmt.signed(s.regime.distance_to_flip, 0)}</Td>
                  <Td>{fmt.signed(s.regime.distance_to_call_wall, 0)}</Td>
                  <Td>{fmt.signed(s.regime.distance_to_put_wall, 0)}</Td>
                  <Td><Badge className={tone.gex(s.regime.regime)}>{s.regime.regime}</Badge></Td>
                  <Td className={s.status === "ok" ? "text-zinc-500" : "text-amber-400"}>{s.status}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {gex?.latest?.converted_to_trading_symbol && (
        <p className="text-[10px] italic text-zinc-500">{gex.latest.converted_to_trading_symbol.disclaimer}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- COT
function CotTable({ cot, onChanged }: { cot: CotView | null; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const refresh = async () => {
    setBusy(true);
    try { await api.cotRefresh(true); onChanged(); } finally { setBusy(false); }
  };
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-zinc-400">
        <Button onClick={refresh} disabled={busy}>{busy ? <Spinner /> : "Check for new report"}</Button>
        <span>{cot?.market ?? "no market data"} · report {cot?.report_date ?? "—"} · as-of {cot?.as_of_date ?? "—"}</span>
        {cot?.staleness && (
          <Badge className={cot.staleness.is_stale
            ? "border-amber-500/50 bg-amber-500/10 text-amber-300"
            : "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"}>
            {cot.staleness.is_stale ? "STALE" : "CURRENT"} · {cot.staleness.note}
          </Badge>
        )}
      </div>
      <p className="text-[10px] italic text-zinc-500">{cot?.proxy_note}</p>
      {!cot || cot.groups.every((g) => g.score == null) ? (
        <EmptyState>No COT data stored yet — click “Check for new report” (free CFTC API, no key).</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead><tr className="border-b border-zinc-800">
              <Th>Group</Th><Th>Report</Th><Th>Long</Th><Th>Short</Th>
              <Th tip="long − short">Net</Th>
              <Th tip="rank of latest net within the lookback window">Pctile</Th>
              <Th>Δ4w</Th><Th>Δ13w</Th>
              <Th tip="|percentile − 50| × 2 — how one-sided positioning is">Crowding</Th>
              <Th tip="(percentile − 50) × 2 → −100 crowded short … +100 crowded long">Score</Th>
              <Th>Label</Th>
            </tr></thead>
            <tbody>
              {cot.groups.map((g) => (
                <tr key={`${g.report_type}-${g.group}`}
                    className={cn("border-b border-zinc-800/50", g.group === "non_commercial" && "bg-zinc-800/20")}>
                  <Td className="text-zinc-200">{g.group.replace(/_/g, " ")} <span className="text-zinc-600">({g.report_type})</span></Td>
                  <Td>{g.report_date ?? "—"}</Td>
                  <Td>{fmt.compact(g.long_positions)}</Td>
                  <Td>{fmt.compact(g.short_positions)}</Td>
                  <Td className={tone.signedScore(g.net_position)}>{fmt.compact(g.net_position)}</Td>
                  <Td>{fmt.num(g.net_percentile)}</Td>
                  <Td>{fmt.compact(g.four_week_change)}</Td>
                  <Td>{fmt.compact(g.thirteen_week_change)}</Td>
                  <Td>{fmt.num(g.crowding_score, 0)}</Td>
                  <Td className={tone.signedScore(g.score)}>{fmt.signed(g.score, 0)}</Td>
                  <Td className="text-zinc-500">{g.label.replace(/_/g, " ")}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- News
function NewsTable({ news, onChanged }: { news: NewsView | null; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const refresh = async () => {
    setBusy(true);
    try { await api.newsRefresh(true); onChanged(); } finally { setBusy(false); }
  };
  const lvl = (v: string) =>
    v === "high" ? "text-red-400" : v === "medium" ? "text-amber-400" : "text-zinc-500";
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-zinc-400">
        <Button onClick={refresh} disabled={busy}>{busy ? <Spinner /> : "Refresh news"}</Button>
        {news?.risk_score && (
          <>
            <span className={cn("font-mono font-bold", tone.signedScore(news.risk_score.score))}>
              Risk score {fmt.signed(news.risk_score.score, 0)}
            </span>
            {news.risk_score.red_folder_flag && (
              <Badge className="border-red-500/60 bg-red-500/15 text-red-300">RED FOLDER TODAY</Badge>
            )}
            <span className="text-zinc-500">{news.risk_score.summary}</span>
          </>
        )}
      </div>
      {!news?.items?.length ? (
        <EmptyState>No scored headlines in the window. Refresh, or set NEWS_API_KEY for a richer provider.</EmptyState>
      ) : (
        <div className="max-h-72 overflow-auto">
          <table className="w-full border-collapse">
            <thead><tr className="border-b border-zinc-800">
              <Th>Time ET</Th><Th>Source</Th><Th>Headline</Th>
              <Th tip="lexicon sentiment, −1…+1">Sent</Th><Th>Vol</Th><Th>Rel</Th><Th>Urg</Th>
            </tr></thead>
            <tbody>
              {news.items.map((n) => (
                <tr key={n.id} className="border-b border-zinc-800/50">
                  <Td>{fmt.nyDateTime(n.timestamp_ny)}</Td>
                  <Td className="text-zinc-500">{n.source ?? "—"}</Td>
                  <Td className="max-w-130 truncate font-sans">
                    <Tooltip wide text={n.matched ? `matched: ${JSON.stringify(n.matched)}` : "no term matches"}>
                      <a href={n.url} target="_blank" rel="noreferrer"
                         className="hover:text-sky-300 hover:underline">
                        {n.red_folder && <span className="mr-1 text-red-400">⚑</span>}{n.title}
                      </a>
                    </Tooltip>
                  </Td>
                  <Td className={n.sentiment > 0.15 ? "text-emerald-400" : n.sentiment < -0.15 ? "text-red-400" : "text-zinc-500"}>
                    {fmt.signed(n.sentiment, 2)}
                  </Td>
                  <Td className={lvl(n.volatility)}>{n.volatility}</Td>
                  <Td className={lvl(n.relevance)}>{n.relevance}</Td>
                  <Td className={lvl(n.urgency)}>{n.urgency}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[10px] italic text-zinc-500">{news?.note}</p>
    </div>
  );
}

// ---------------------------------------------------------------- Kronos import/history
function KronosTab({ kronos, onChanged }: { kronos: KronosView | null; onChanged: () => void }) {
  const [text, setText] = useState("");
  const [format, setFormat] = useState<"json" | "csv">("json");
  const [horizon, setHorizon] = useState<"hourly" | "daily">("hourly");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const doImport = async () => {
    setBusy(true); setMsg(null);
    try {
      const body = format === "csv"
        ? { format: "csv", csv: text, horizon }
        : { format: "json", data: JSON.parse(text) };
      const r = await api.kronosImport(body);
      setMsg({ ok: true, text: `Imported forecast #${r.forecast_id} (${r.direction}, ${r.points} points).` });
      setText("");
      onChanged();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally { setBusy(false); }
  };

  const runLocal = async (h: "hourly" | "daily") => {
    setBusy(true); setMsg(null);
    try {
      await api.kronosRun(h);
      setMsg({ ok: true, text: `Local Kronos ${h} run complete.` });
      onChanged();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally { setBusy(false); }
  };

  const avail = kronos?.availability;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="flex flex-col gap-2">
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          Import forecast (Mode A)
        </h4>
        <div className="flex items-center gap-2 text-[11px]">
          <select value={format} onChange={(e) => setFormat(e.target.value as "json" | "csv")}
                  className="rounded border border-zinc-700 bg-zinc-800 px-1.5 py-1 text-zinc-200">
            <option value="json">JSON</option><option value="csv">CSV</option>
          </select>
          {format === "csv" && (
            <select value={horizon} onChange={(e) => setHorizon(e.target.value as "hourly" | "daily")}
                    className="rounded border border-zinc-700 bg-zinc-800 px-1.5 py-1 text-zinc-200">
              <option value="hourly">hourly</option><option value="daily">daily</option>
            </select>
          )}
          <Button variant="primary" onClick={doImport} disabled={busy || !text.trim()}>
            {busy ? <Spinner /> : "Import"}
          </Button>
        </div>
        <textarea
          value={text} onChange={(e) => setText(e.target.value)}
          placeholder={format === "json"
            ? '{"symbol":"MES","horizon":"hourly","path":[["2026-06-12T14:00:00Z",6010],...],"band_upper":[...],"band_lower":[...],"confidence":70}'
            : "timestamp,value,upper,lower\n2026-06-12T14:00:00Z,6010,6030,5990\n…"}
          className="h-28 w-full rounded border border-zinc-700 bg-zinc-950 p-2 font-mono text-[10px] text-zinc-300 placeholder:text-zinc-600"
        />
        {msg && (msg.ok
          ? <p className="text-[11px] text-emerald-400">{msg.text}</p>
          : <ErrorState>{msg.text}</ErrorState>)}
        <div className="flex items-center gap-2 text-[11px] text-zinc-400">
          <span className="font-semibold uppercase tracking-wider text-zinc-500">Local runner (Mode B):</span>
          {avail?.local_runner_available && avail.local_runner_enabled ? (
            <>
              <Button onClick={() => runLocal("hourly")} disabled={busy}>Run 1H</Button>
              <Button onClick={() => runLocal("daily")} disabled={busy}>Run 1D</Button>
              <span className="text-zinc-600">(CPU inference — takes minutes)</span>
            </>
          ) : (
            <span className="text-zinc-500">
              {avail?.local_runner_enabled === false
                ? "disabled (ENABLE_LOCAL_KRONOS=false)"
                : avail?.reason ?? "unavailable"}
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Forecast history</h4>
        {!kronos?.history?.length ? (
          <EmptyState>No forecasts stored.</EmptyState>
        ) : (
          <div className="max-h-60 overflow-auto">
            <table className="w-full border-collapse">
              <thead><tr className="border-b border-zinc-800">
                <Th>#</Th><Th>Horizon</Th><Th>Dir</Th><Th>Conf</Th><Th>Source</Th>
                <Th>Generated ET</Th><Th>Window ET</Th><Th>Pts</Th>
              </tr></thead>
              <tbody>
                {kronos.history.map((h) => (
                  <tr key={h.id} className="border-b border-zinc-800/50">
                    <Td>{h.id}</Td>
                    <Td>{h.horizon}</Td>
                    <Td className={tone.direction(h.direction)}>{h.direction}</Td>
                    <Td>{fmt.num(h.confidence, 0)}</Td>
                    <Td className="text-zinc-500">{h.source}</Td>
                    <Td>{fmt.nyDateTime(h.generated_at_ny)}</Td>
                    <Td className="text-zinc-500">
                      {fmt.nyTime(h.forecast_start_ny)}–{fmt.nyTime(h.forecast_end_ny)}
                    </Td>
                    <Td>{h.points}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- regime history
function RegimeHistory({ regime }: { regime: RegimeView | null }) {
  const rows = regime ? [regime.current, ...regime.history].filter(Boolean) : [];
  if (!rows.length) return <EmptyState>No regime snapshots yet.</EmptyState>;
  return (
    <div className="max-h-72 overflow-auto">
      <table className="w-full border-collapse">
        <thead><tr className="border-b border-zinc-800">
          <Th>Time ET</Th><Th>Bias</Th><Th>Environment</Th><Th>Conf</Th>
          <Th>Kronos</Th><Th>GEX</Th><Th>COT</Th><Th>News</Th><Th>Top reason</Th>
        </tr></thead>
        <tbody>
          {rows.map((r) => r && (
            <tr key={r.id} className="border-b border-zinc-800/50">
              <Td>{fmt.nyDateTime(r.timestamp_ny)}</Td>
              <Td><Badge className={tone.bias(r.bias)}>{label.bias(r.bias)}</Badge></Td>
              <Td>{label.environment(r.environment)}</Td>
              <Td className={tone.score(r.confidence)}>{Math.round(r.confidence)}</Td>
              <Td>{fmt.num(r.kronos_score, 0)}</Td>
              <Td>{fmt.signed(r.gex_score, 0)}</Td>
              <Td>{fmt.signed(r.cot_score, 0)}</Td>
              <Td>{fmt.signed(r.news_score, 0)}</Td>
              <Td className="max-w-110 truncate font-sans text-zinc-400">{r.reasons[0] ?? "—"}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
