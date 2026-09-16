import { useCallback, useEffect, useRef, useState } from "react";
import { getMetrics } from "../api/runtime";
import type { MetricsResponse } from "../api/types";

export function useRuntimeMetrics(intervalMs = 10_000) {
  const [data, setData] = useState<MetricsResponse>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);
  const inFlight = useRef<Promise<void> | null>(null);

  const refresh = useCallback(() => {
    if (inFlight.current) return inFlight.current;
    setLoading(true);
    const request = (async () => {
      try {
        const next = await getMetrics();
        if (!mounted.current) return;
        setData(next);
        setError(undefined);
      } catch (nextError) {
        if (mounted.current) setError(nextError);
      } finally {
        if (mounted.current) setLoading(false);
      }
    })();
    inFlight.current = request.finally(() => {
      inFlight.current = null;
    });
    return inFlight.current;
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => void refresh(), intervalMs);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
    };
  }, [intervalMs, refresh]);

  return { data, error, loading, refresh };
}
