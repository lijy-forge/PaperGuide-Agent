import { apiClient } from "./client";
import type { HealthResponse, MetricsResponse } from "./types";

export async function getHealth(
  endpoint: "live" | "ready" = "ready"
): Promise<HealthResponse> {
  return (await apiClient.get<HealthResponse>(`/health/${endpoint}`, {
    // Readiness deliberately uses HTTP 503 for a reachable but degraded runtime.
    validateStatus: (status) => status === 200 || status === 503
  })).data;
}

/** Existing dashboard compatibility alias. */
export const getReadiness = () => getHealth("ready");

export async function getMetrics(): Promise<MetricsResponse> {
  return (await apiClient.get<MetricsResponse>("/api/v1/metrics")).data;
}
