import { useCallback, useEffect, useRef, useState } from "react";
import { getHealth } from "../api/runtime";
import type { HealthResponse } from "../api/types";

export type HealthState =
  | "checking"
  | "ready"
  | "host_offline"
  | "degraded"
  | "api_offline";

function classifyHealth(response: HealthResponse): HealthState {
  if (response.ready) return "ready";
  const host = response.checks.find((check) => check.name === "host_heartbeat");
  return host && !host.healthy ? "host_offline" : "degraded";
}

export function useRuntimeHealth(intervalMs = 10_000) {
  const [state, setState] = useState<HealthState>("checking");
  const [health, setHealth] = useState<HealthResponse>();
  const [error, setError] = useState<unknown>();
  const mounted = useRef(true);
  const inFlight = useRef<Promise<void> | null>(null);

  const refresh = useCallback(() => {
    if (inFlight.current) return inFlight.current;
    const request = (async () => {
      try {
        const next = await getHealth("ready");
        if (!mounted.current) return;
        setHealth(next);
        setError(undefined);
        setState(classifyHealth(next));
      } catch (nextError) {
        if (!mounted.current) return;
        setError(nextError);
        setState("api_offline");
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

  return { state, health, error, refresh };
}
