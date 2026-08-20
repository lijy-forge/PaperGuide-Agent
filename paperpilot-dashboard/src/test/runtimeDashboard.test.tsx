import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RuntimeMetrics } from "../components/RuntimeMetrics";
import { useRuntimeHealth } from "../hooks/useRuntimeHealth";
import { useRuntimeMetrics } from "../hooks/useRuntimeMetrics";
import type { HealthResponse, MetricsResponse } from "../api/types";

const getHealth = vi.fn();
const getMetrics = vi.fn();
vi.mock("../api/runtime", () => ({
  getHealth: (...args: unknown[]) => getHealth(...args),
  getMetrics: (...args: unknown[]) => getMetrics(...args)
}));

const ready: HealthResponse = {
  kind: "readiness",
  status: "healthy",
  ready: true,
  checks: [{ name: "host_heartbeat", healthy: true }]
};
const metrics: MetricsResponse = {
  submitted_total: 1,
  completed_total: 2,
  failed_total: 3,
  cancelled_total: 4,
  dead_letter_total: 5,
  active_workers: 6,
  queue_size: 7,
  running_tasks: 8,
  lease_expired_total: 9,
  stale_worker_rejected_total: 10,
  average_execution_time_ms: 750
};

describe("runtime health", () => {
  beforeEach(() => {
    getHealth.mockReset();
    getMetrics.mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("starts in checking state", () => {
    getHealth.mockReturnValue(new Promise(() => undefined));
    const { result, unmount } = renderHook(() => useRuntimeHealth());
    expect(result.current.state).toBe("checking");
    unmount();
  });

  it("maps a ready response", async () => {
    getHealth.mockResolvedValue(ready);
    const { result } = renderHook(() => useRuntimeHealth());
    await waitFor(() => expect(result.current.state).toBe("ready"));
    expect(getHealth).toHaveBeenCalledWith("ready");
  });

  it("maps a failed host heartbeat to Host Offline", async () => {
    getHealth.mockResolvedValue({
      ...ready,
      ready: false,
      status: "unhealthy",
      checks: [{ name: "host_heartbeat", healthy: false }]
    });
    const { result } = renderHook(() => useRuntimeHealth());
    await waitFor(() => expect(result.current.state).toBe("host_offline"));
  });

  it("maps other failed checks to Runtime Degraded", async () => {
    getHealth.mockResolvedValue({
      ...ready,
      ready: false,
      status: "unhealthy",
      checks: [{ name: "schema_version", healthy: false }]
    });
    const { result } = renderHook(() => useRuntimeHealth());
    await waitFor(() => expect(result.current.state).toBe("degraded"));
  });

  it("maps a network error to API Offline", async () => {
    getHealth.mockRejectedValue(new Error("private path"));
    const { result } = renderHook(() => useRuntimeHealth());
    await waitFor(() => expect(result.current.state).toBe("api_offline"));
  });

  it("prevents overlapping manual health requests", async () => {
    let resolveRequest: ((value: HealthResponse) => void) | undefined;
    getHealth.mockReturnValue(
      new Promise<HealthResponse>((resolve) => {
        resolveRequest = resolve;
      })
    );
    const { result } = renderHook(() => useRuntimeHealth());
    act(() => {
      void result.current.refresh();
      void result.current.refresh();
    });
    expect(getHealth).toHaveBeenCalledTimes(1);
    await act(async () => resolveRequest?.(ready));
  });

  it("refreshes health on the configured interval and cleans up", async () => {
    vi.useFakeTimers();
    getHealth.mockResolvedValue(ready);
    const { unmount } = renderHook(() => useRuntimeHealth(10_000));
    await act(async () => Promise.resolve());
    expect(getHealth).toHaveBeenCalledTimes(1);
    await act(async () => {
      vi.advanceTimersByTime(10_000);
      await Promise.resolve();
    });
    expect(getHealth).toHaveBeenCalledTimes(2);
    unmount();
    vi.advanceTimersByTime(20_000);
    expect(getHealth).toHaveBeenCalledTimes(2);
  });
});

describe("runtime metrics", () => {
  beforeEach(() => {
    getMetrics.mockReset();
    getHealth.mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("loads all public metrics", async () => {
    getMetrics.mockResolvedValue(metrics);
    const { result } = renderHook(() => useRuntimeMetrics());
    await waitFor(() => expect(result.current.data).toEqual(metrics));
    expect(result.current.loading).toBe(false);
  });

  it("retains the previous successful metrics after refresh failure", async () => {
    getMetrics.mockResolvedValueOnce(metrics);
    const { result } = renderHook(() => useRuntimeMetrics());
    await waitFor(() => expect(result.current.data).toEqual(metrics));
    getMetrics.mockRejectedValueOnce(new Error("offline"));
    await act(async () => result.current.refresh());
    expect(result.current.data).toEqual(metrics);
    expect(result.current.error).toBeInstanceOf(Error);
  });

  it("renders zero values when there is no historical data", () => {
    render(<RuntimeMetrics />);
    expect(document.querySelectorAll(".metric-card")).toHaveLength(9);
    expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(8);
    expect(screen.getByText("0 毫秒")).toBeTruthy();
  });

  it("refreshes metrics automatically without overlapping requests", async () => {
    vi.useFakeTimers();
    getMetrics.mockResolvedValue(metrics);
    const { result, unmount } = renderHook(() => useRuntimeMetrics(10_000));
    await act(async () => Promise.resolve());
    await act(async () => {
      void result.current.refresh();
      void result.current.refresh();
    });
    expect(getMetrics).toHaveBeenCalledTimes(2);
    await act(async () => {
      vi.advanceTimersByTime(10_000);
      await Promise.resolve();
    });
    expect(getMetrics).toHaveBeenCalledTimes(3);
    unmount();
  });
});
