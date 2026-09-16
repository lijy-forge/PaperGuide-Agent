import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { useTaskEvents } from "../hooks/useTaskEvents";
import { TASK_POLL_INTERVAL_MS, useTaskPolling } from "../hooks/useTaskPolling";
import type { TaskEventResponse, TaskStatus, TaskStatusResponse } from "../api/types";

const getTask = vi.fn();
const getTaskEvents = vi.fn();
vi.mock("../api/tasks", () => ({ getTask: (...args: unknown[]) => getTask(...args), getTaskEvents: (...args: unknown[]) => getTaskEvents(...args) }));

const task = (status: TaskStatus): TaskStatusResponse => ({ task_id: "task", run_id: "run", status, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:01Z", artifact_available: status === "completed", artifact_format: status === "completed" ? "markdown" : null, human_review_required: false, retryable: false, error_code: null });
const event = (id: number): TaskEventResponse => ({ event_id: id, event_type: id === 1 ? "task_created" : "task_started", status: id === 1 ? "queued" : "running", attempt_count: 1, duration_ms: null, created_at: "2026-01-01T00:00:00Z" });

describe("task polling", () => {
  beforeEach(() => { getTask.mockReset(); getTaskEvents.mockReset(); });
  it("uses the five-second production interval", () => { expect(TASK_POLL_INTERVAL_MS).toBe(5_000); });
  it("polls an active task", async () => { getTask.mockResolvedValue(task("running")); const { unmount } = renderHook(() => useTaskPolling("task", 20)); await waitFor(() => expect(getTask).toHaveBeenCalledTimes(1)); await new Promise((resolve) => setTimeout(resolve, 30)); await waitFor(() => expect(getTask.mock.calls.length).toBeGreaterThan(1)); unmount(); });
  it("stops after terminal status", async () => { getTask.mockResolvedValue(task("completed")); const { unmount } = renderHook(() => useTaskPolling("task", 10)); await waitFor(() => expect(getTask).toHaveBeenCalledTimes(1)); await new Promise((resolve) => setTimeout(resolve, 30)); expect(getTask).toHaveBeenCalledTimes(1); unmount(); });
  it("stops after task 404", async () => { getTask.mockRejectedValue(new ApiError("NOT_FOUND", "missing", "rid", 404)); const { result } = renderHook(() => useTaskPolling("task", 10)); await waitFor(() => expect(result.current.error).toBeInstanceOf(ApiError)); await new Promise((resolve) => setTimeout(resolve, 30)); expect(getTask).toHaveBeenCalledTimes(1); });
  it("recovers after a network failure", async () => { getTask.mockRejectedValueOnce(new ApiError("OFFLINE", "offline", undefined, undefined)).mockResolvedValue(task("completed")); const { result } = renderHook(() => useTaskPolling("task", 10)); await waitFor(() => expect(result.current.task?.status).toBe("completed"), { timeout: 500 }); expect(getTask).toHaveBeenCalledTimes(2); });
  it("cleans up the scheduled timer on unmount", async () => { const clearTimer = vi.spyOn(window, "clearTimeout"); getTask.mockResolvedValue(task("running")); const { unmount } = renderHook(() => useTaskPolling("task", 1_000)); await waitFor(() => expect(getTask).toHaveBeenCalledOnce()); unmount(); expect(clearTimer).toHaveBeenCalled(); });
});

describe("event polling", () => {
  beforeEach(() => getTaskEvents.mockReset());
  it("exposes loading state and prevents duplicate refresh requests", async () => { let resolveEvents: ((value: TaskEventResponse[]) => void) | undefined; getTaskEvents.mockReturnValue(new Promise((resolve) => { resolveEvents = resolve; })); const { result } = renderHook(() => useTaskEvents("task")); expect(result.current.loading).toBe(true); await act(async () => { void result.current.refresh(); void result.current.refresh(); }); expect(getTaskEvents).toHaveBeenCalledOnce(); resolveEvents?.([event(1)]); await waitFor(() => expect(result.current.loading).toBe(false)); });
  it("loads the first twenty-event page", async () => { getTaskEvents.mockResolvedValue([event(1)]); const { result } = renderHook(() => useTaskEvents("task", false)); await waitFor(() => expect(result.current.events).toHaveLength(1)); expect(getTaskEvents).toHaveBeenCalledWith("task", 20, 0); });
  it("uses offset pagination", async () => { getTaskEvents.mockResolvedValueOnce(Array.from({ length: 20 }, (_, index) => event(index + 1))).mockResolvedValueOnce([event(21)]); const { result } = renderHook(() => useTaskEvents("task", false)); await waitFor(() => expect(result.current.events).toHaveLength(20)); await act(async () => result.current.loadMore()); expect(getTaskEvents).toHaveBeenLastCalledWith("task", 20, 20); expect(result.current.events).toHaveLength(21); });
  it("deduplicates refreshed event ids", async () => { getTaskEvents.mockResolvedValue([event(1), event(1), event(2)]); const { result } = renderHook(() => useTaskEvents("task", false)); await waitFor(() => expect(result.current.events).toHaveLength(2)); expect(result.current.events.map((item) => item.event_id)).toEqual([1, 2]); });
  it("polls events while the task is active", async () => { getTaskEvents.mockResolvedValue([event(1)]); const { unmount } = renderHook(() => useTaskEvents("task", true, 10)); await waitFor(() => expect(getTaskEvents).toHaveBeenCalledTimes(1)); await new Promise((resolve) => setTimeout(resolve, 30)); await waitFor(() => expect(getTaskEvents.mock.calls.length).toBeGreaterThan(1)); unmount(); });
  it("does not poll events for an inactive task", async () => { getTaskEvents.mockResolvedValue([event(1)]); renderHook(() => useTaskEvents("task", false, 10)); await waitFor(() => expect(getTaskEvents).toHaveBeenCalledTimes(1)); await new Promise((resolve) => setTimeout(resolve, 30)); expect(getTaskEvents).toHaveBeenCalledTimes(1); });
  it("finishes persisted history for a terminal task", async () => {
    getTaskEvents
      .mockResolvedValueOnce(Array.from({ length: 20 }, (_, index) => event(index + 1)))
      .mockResolvedValueOnce([event(21)]);
    const { result, unmount } = renderHook(() => useTaskEvents("task", false, 10));
    await waitFor(() => expect(getTaskEvents).toHaveBeenCalledWith("task", 20, 0, 20));
    await waitFor(() => expect(result.current.events).toHaveLength(21));
    unmount();
  });
  it("refreshes events explicitly", async () => { getTaskEvents.mockResolvedValue([event(1)]); const { result } = renderHook(() => useTaskEvents("task")); await waitFor(() => expect(getTaskEvents).toHaveBeenCalledOnce()); await act(async () => result.current.refresh()); expect(getTaskEvents).toHaveBeenCalledTimes(2); });
});
