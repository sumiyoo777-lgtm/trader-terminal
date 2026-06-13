"use client";
// Main terminal chart: live MES candles + raw Kronos path + forecast bands +
// Kronos-guided Kalman estimate + gamma levels + forecast-failure markers.
import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  LineSeries,
  LineStyle,
  ColorType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Candle, GexSnapshotView, KronosView } from "@/lib/types";
import { Badge, EmptyState } from "@/components/ui";

const NY_FMT = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", month: "short", day: "numeric",
  hour: "2-digit", minute: "2-digit", hour12: false,
});
const NY_TIME_ONLY = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false,
});

const toTs = (iso: string): UTCTimestamp =>
  Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;

export function MainChart({
  candles,
  kronos,
  kronosDaily,
  gex,
}: {
  candles: Candle[];
  kronos: KronosView | null;
  kronosDaily: KronosView | null;
  gex: GexSnapshotView | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || candles.length === 0) return;

    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#0c0c0f" },
        textColor: "#9ca3af",
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "#1c1c22" },
        horzLines: { color: "#1c1c22" },
      },
      rightPriceScale: { borderColor: "#27272a" },
      timeScale: {
        borderColor: "#27272a",
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (t: UTCTimestamp) => NY_TIME_ONLY.format(new Date(t * 1000)),
      },
      localization: {
        timeFormatter: (t: UTCTimestamp) => `${NY_FMT.format(new Date(t * 1000))} ET`,
      },
      crosshair: { mode: 0 },
    });
    chartRef.current = chart;

    // --- live MES candles -------------------------------------------------
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981", downColor: "#ef4444",
      wickUpColor: "#10b981", wickDownColor: "#ef4444",
      borderVisible: false,
    });
    candleSeries.setData(
      candles.map((c) => ({
        time: toTs(c.timestamp), open: c.open, high: c.high, low: c.low, close: c.close,
      })),
    );

    // --- Kronos hourly forecast + bands + Kalman estimate ------------------
    const series = kronos?.status === "ok" ? kronos.series : null;
    if (series) {
      const times = series.timestamps.map(toTs);

      const kronosLine = chart.addSeries(LineSeries, {
        color: "#f59e0b", lineWidth: 2, title: "Kronos 1H",
        lastValueVisible: false, priceLineVisible: false,
      });
      kronosLine.setData(times.map((t, i) => ({ time: t, value: series.kronos_path[i] })));

      if (series.band_upper && series.band_lower) {
        for (const [band, title] of [
          [series.band_upper, "band+"],
          [series.band_lower, "band-"],
        ] as const) {
          const line = chart.addSeries(LineSeries, {
            color: "#92702a", lineWidth: 1, lineStyle: LineStyle.Dotted,
            title, lastValueVisible: false, priceLineVisible: false,
            crosshairMarkerVisible: false,
          });
          line.setData(times.map((t, i) => ({ time: t, value: band[i] })));
        }
      }

      const kalmanLine = chart.addSeries(LineSeries, {
        color: "#a78bfa", lineWidth: 2, lineStyle: LineStyle.Dashed,
        title: "Kalman", lastValueVisible: false, priceLineVisible: false,
      });
      kalmanLine.setData(
        times.flatMap((t, i) =>
          series.kalman_estimate[i] == null ? [] : [{ time: t, value: series.kalman_estimate[i]! }],
        ),
      );

      // forecast-failure zones: mark observed points with |z| > 2.5
      const failureMarkers = times.flatMap((t, i) => {
        const z = series.residual_z[i];
        if (z == null || Math.abs(z) <= 2.5) return [];
        const position: "aboveBar" | "belowBar" = z > 0 ? "aboveBar" : "belowBar";
        return [{
          time: t,
          position,
          color: "#ef4444",
          shape: "circle" as const,
          text: `z ${z.toFixed(1)}`,
        }];
      });
      if (failureMarkers.length) createSeriesMarkers(kronosLine, failureMarkers);
    }

    // --- Kronos daily forecast overlay (when toggled) -----------------------
    const daily = kronosDaily?.status === "ok" ? kronosDaily.series : null;
    if (daily) {
      const dailyLine = chart.addSeries(LineSeries, {
        color: "#38bdf8", lineWidth: 1, lineStyle: LineStyle.SparseDotted,
        title: "Kronos 1D", lastValueVisible: false, priceLineVisible: false,
      });
      dailyLine.setData(
        daily.timestamps.map((ts, i) => ({ time: toTs(ts), value: daily.kronos_path[i] })),
      );
    }

    // --- gamma levels (converted to MES scale — approximate) ---------------
    const conv = gex?.converted_to_trading_symbol;
    const levels: [number | null | undefined, string, string][] = [
      [conv?.gamma_flip, "γ-flip ≈", "#eab308"],
      [conv?.call_wall, "call wall ≈", "#0ea5e9"],
      [conv?.put_wall, "put wall ≈", "#e879f9"],
    ];
    for (const [price, title, color] of levels) {
      if (price == null) continue;
      candleSeries.createPriceLine({
        price, color, lineWidth: 1, lineStyle: LineStyle.LargeDashed,
        axisLabelVisible: true, title,
      });
    }

    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, kronos, kronosDaily, gex]);

  if (candles.length === 0) {
    return (
      <EmptyState>
        No price history yet. Click “Refresh all” (or POST /prices/refresh) to pull MES candles.
      </EmptyState>
    );
  }

  return (
    <div>
      <div ref={containerRef} className="h-105 w-full" />
      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px] text-zinc-500">
        <LegendSwatch color="#10b981" label="MES (live)" />
        <LegendSwatch color="#f59e0b" label="Kronos 1H path" />
        <LegendSwatch color="#92702a" label="forecast band (±2σ)" />
        <LegendSwatch color="#a78bfa" label="Kronos-guided Kalman" />
        <LegendSwatch color="#38bdf8" label="Kronos 1D" />
        <LegendSwatch color="#ef4444" label="failure zone (|z|>2.5)" />
        {gex?.converted_to_trading_symbol && (
          <Badge className="border-amber-600/40 bg-amber-600/10 text-amber-400">
            γ levels ≈ approximate ({gex.symbol}→{gex.proxy_for})
          </Badge>
        )}
      </div>
    </div>
  );
}

function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="inline-block h-0.5 w-3 rounded" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}
