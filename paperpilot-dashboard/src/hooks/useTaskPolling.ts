import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { getTask } from "../api/tasks";
import type { TaskStatusResponse } from "../api/types";
import { isTerminal } from "../utils/taskStatus";

export const TASK_POLL_INTERVAL_MS = 5_000;

export function useTask(taskId: string, pollIntervalMs = TASK_POLL_INTERVAL_MS) {
  const [task, setTask] = useState<TaskStatusResponse>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const stopped = useRef(false);
  const inFlight = useRef(false);
  const failures = useRef(0);
  const timer = useRef<number>();
  const mounted = useRef(false);

  const refresh = useCallback(async () => {
    if (!taskId || inFlight.current || stopped.current) return;
    inFlight.current = true;
    try {
      const next = await getTask(taskId);
      failures.current = 0;
      if (mounted.current) {
        setTask(next);
        setError(undefined);
      }
      if (isTerminal(next.status)) stopped.current = true;
    } catch (nextError) {
      if (mounted.current) setError(nextError);
      failures.current += 1;
      if (nextError instanceof ApiError && nextError.status === 404) stopped.current = true;
    } finally {
      inFlight.current = false;
      if (mounted.current) setLoading(false);
      if (mounted.current && !stopped.current) {
        timer.current = window.setTimeout(() => void refresh(), pollIntervalMs);
      }
    }
  }, [pollIntervalMs, taskId]);

  useEffect(() => {
    mounted.current = true;
    stopped.current = false;
    failures.current = 0;
    void refresh();
    return () => {
      mounted.current = false;
      stopped.current = true;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [refresh]);

  const refreshNow = useCallback(async () => {
    if (timer.current) window.clearTimeout(timer.current);
    stopped.current = false;
    await refresh();
  }, [refresh]);

  return { task, error, loading, refresh: refreshNow };
}

/** Backwards-compatible name retained for existing imports. */
export const useTaskPolling = useTask;
