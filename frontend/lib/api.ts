// Typed API client. All endpoints are same-origin (proxied to FastAPI by
// next.config.ts rewrites).
import type {
  AlertView,
  CotView,
  GexView,
  KronosView,
  NewsView,
  PricesView,
  RegimeView,
  Summary,
} from "./types";

const BASE = "/api/trader-terminal";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  summary: () => request<Summary>("/summary"),
  kronos: (slider: number, horizon: "hourly" | "daily" = "hourly") =>
    request<KronosView>(`/kronos?slider=${slider}&horizon=${horizon}`),
  kronosImport: (body: Record<string, unknown>) =>
    request<{ ok: boolean; forecast_id: number; direction: string; points: number }>(
      "/kronos/import",
      { method: "POST", body: JSON.stringify(body) },
    ),
  kronosRun: (horizon: "hourly" | "daily") =>
    request<{ ok: boolean }>(`/kronos/run?horizon=${horizon}`, { method: "POST" }),
  gex: () => request<GexView>("/gex"),
  gexRefresh: () =>
    request<{ ok: boolean; kind?: string; message?: string }>("/gex/refresh", { method: "POST" }),
  cot: () => request<CotView>("/cot"),
  cotRefresh: (force = false) =>
    request<{ ok: boolean }>(`/cot/refresh?force=${force}`, { method: "POST" }),
  news: () => request<NewsView>("/news"),
  newsRefresh: (force = false) =>
    request<{ ok: boolean }>(`/news/refresh?force=${force}`, { method: "POST" }),
  regime: () => request<RegimeView>("/regime"),
  regimeRecalculate: (slider?: number) =>
    request<RegimeView["current"]>(
      `/regime/recalculate${slider != null ? `?slider=${slider}` : ""}`,
      { method: "POST" },
    ),
  alerts: () => request<{ alerts: AlertView[] }>("/alerts"),
  acknowledgeAlert: (id: number) =>
    request<{ ok: boolean }>(`/alerts/${id}/acknowledge`, { method: "POST" }),
  prices: (hoursBack = 30) => request<PricesView>(`/prices?hours_back=${hoursBack}`),
  pricesRefresh: () => request<{ ok: boolean }>("/prices/refresh", { method: "POST" }),
};
