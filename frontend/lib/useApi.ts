"use client";
// Minimal polling data hook: load, error, refresh, interval re-fetch.
import { useCallback, useEffect, useRef, useState } from "react";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
  lastFetched: Date | null;
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  { intervalMs, deps = [] }: { intervalMs?: number; deps?: unknown[] } = {},
): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastFetched, setLastFetched] = useState<Date | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      setData(result);
      setError(null);
      setLastFetched(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void refresh();
    if (!intervalMs) return;
    const id = setInterval(() => void refresh(), intervalMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, refresh, ...deps]);

  return { data, error, loading, refresh, lastFetched };
}
