"use client";
// /dashboard/trader-terminal — the terminal page. Composes every panel and
// owns the polling cadence + the Kalman trust slider state.
import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { ControlBar } from "@/components/terminal/ControlBar";
import { ScoreRow } from "@/components/terminal/ScoreRow";
import { MainChart } from "@/components/terminal/MainChart";
import { KronosPanel } from "@/components/terminal/KronosPanel";
import { AlertsCard, DataHealthCard, RegimeCard } from "@/components/terminal/SidePanel";
import { BottomPanels } from "@/components/terminal/BottomPanels";
import { Card, ErrorState } from "@/components/ui";

const POLL = {
  summary: 30_000,
  kronos: 60_000,
  prices: 60_000,
  gex: 120_000,
  cot: 600_000,
  news: 120_000,
  regime: 60_000,
  alerts: 30_000,
};

export default function TraderTerminalPage() {
  const [slider, setSlider] = useState(50);
  const [showDaily, setShowDaily] = useState(false);
  const [refreshingAll, setRefreshingAll] = useState(false);

  const summary = useApi(() => api.summary(), { intervalMs: POLL.summary });
  const kronos = useApi(() => api.kronos(slider, "hourly"), { intervalMs: POLL.kronos, deps: [slider] });
  const kronosDaily = useApi(() => api.kronos(slider, "daily"), { intervalMs: POLL.kronos, deps: [slider] });
  const prices = useApi(() => api.prices(36), { intervalMs: POLL.prices });
  const gex = useApi(() => api.gex(), { intervalMs: POLL.gex });
  const cot = useApi(() => api.cot(), { intervalMs: POLL.cot });
  const news = useApi(() => api.news(), { intervalMs: POLL.news });
  const regime = useApi(() => api.regime(), { intervalMs: POLL.regime });
  const alerts = useApi(() => api.alerts(), { intervalMs: POLL.alerts });

  const refreshViews = useCallback(() => {
    void summary.refresh(); void kronos.refresh(); void kronosDaily.refresh();
    void gex.refresh(); void cot.refresh(); void news.refresh();
    void regime.refresh(); void alerts.refresh(); void prices.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshAll = useCallback(async () => {
    setRefreshingAll(true);
    try {
      // pull fresh source data, then recalculate the regime, then re-read views
      await Promise.allSettled([
        api.pricesRefresh(),
        api.newsRefresh(),
        api.cotRefresh(),
      ]);
      await api.regimeRecalculate(slider).catch(() => null);
      refreshViews();
    } finally {
      setRefreshingAll(false);
    }
  }, [slider, refreshViews]);

  const acknowledge = useCallback(async (id: number) => {
    await api.acknowledgeAlert(id);
    void alerts.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const backendDown = summary.error != null && summary.data == null;

  return (
    <main className="mx-auto flex min-h-screen max-w-450 flex-col gap-3 p-3">
      <ControlBar
        summary={summary.data}
        loading={summary.loading}
        onRefreshAll={() => void refreshAll()}
        refreshing={refreshingAll}
      />

      {backendDown && (
        <ErrorState>
          Backend unreachable ({summary.error}). Start it with{" "}
          <code className="font-mono">uvicorn app.main:app --port 8000</code> from{" "}
          <code className="font-mono">backend/</code>.
        </ErrorState>
      )}

      <ScoreRow summary={summary.data} />

      <div className="grid gap-3 xl:grid-cols-[1fr_360px]">
        <div className="flex min-w-0 flex-col gap-3">
          <Card
            title={`${summary.data?.symbol ?? "MES"} — live vs Kronos intended path`}
            right={
              <label className="flex cursor-pointer items-center gap-1.5 text-[10px] text-zinc-400">
                <input
                  type="checkbox"
                  checked={showDaily}
                  onChange={(e) => setShowDaily(e.target.checked)}
                  className="accent-sky-400"
                />
                overlay 1D forecast
              </label>
            }
          >
            {prices.error && <ErrorState>price feed: {prices.error}</ErrorState>}
            <MainChart
              candles={prices.data?.candles ?? []}
              kronos={kronos.data}
              kronosDaily={showDaily ? kronosDaily.data : null}
              gex={gex.data?.latest ?? null}
            />
          </Card>

          <KronosPanel view={kronos.data} slider={slider} onSliderChange={setSlider} />

          <BottomPanels
            gex={gex.data}
            cot={cot.data}
            news={news.data}
            kronos={kronos.data}
            regime={regime.data}
            onChanged={refreshViews}
          />
        </div>

        <div className="flex flex-col gap-3">
          <RegimeCard regime={regime.data?.current ?? null} />
          <AlertsCard alerts={alerts.data?.alerts ?? []} onAcknowledge={(id) => void acknowledge(id)} />
          <DataHealthCard summary={summary.data} />
        </div>
      </div>

      <footer className="pb-2 text-center text-[10px] text-zinc-600">
        Research / decision-support terminal for forward testing and discretionary MES trading.
        No broker connection · no order execution · GEX levels on MES are approximate proxy
        conversions · COT is weekly positioning, not intraday timing.
      </footer>
    </main>
  );
}
