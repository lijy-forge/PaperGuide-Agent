import { useCallback, useEffect, useRef, useState } from "react";
import { getTaskEvents } from "../api/tasks";
import type { TaskEventResponse } from "../api/types";

const PAGE_SIZE = 20;
export const EVENT_POLL_INTERVAL_MS = 2_000;

function mergeEvents(current: TaskEventResponse[], incoming: TaskEventResponse[]): TaskEventResponse[] {
  return [...new Map([...current, ...incoming].map((event) => [event.event_id, event])).values()].sort((a, b) => a.event_id - b.event_id);
}

export function useTaskEvents(
  taskId: string,
  active = false,
  pollIntervalMs = EVENT_POLL_INTERVAL_MS
) {
  const [events, setEvents] = useState<TaskEventResponse[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const inFlight = useRef(false);
  const pageInFlight = useRef(false);
  const mounted = useRef(false);
  const timer = useRef<number>();
  const lastEventId = useRef<number>();

  const refresh = useCallback(async () => {
    if (!taskId || inFlight.current) return;
    inFlight.current = true;
    let pageLength = 0;
    if (mounted.current) {
      setLoading(true);
      setRefreshing(true);
    }
    try {
      const page = lastEventId.current == null
        ? await getTaskEvents(taskId, PAGE_SIZE, 0)
        : await getTaskEvents(taskId, PAGE_SIZE, 0, lastEventId.current);
      pageLength = page.length;
      if (mounted.current) {
        setEvents((current) => mergeEvents(current, page));
        if (page.length) lastEventId.current = Math.max(lastEventId.current ?? 0, ...page.map((event) => event.event_id));
        setHasMore(page.length === PAGE_SIZE);
        setError(undefined);
      }
    } catch (nextError) {
      if (mounted.current) setError(nextError);
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        setLoading(false);
        setRefreshing(false);
        // A terminal task may have more persisted history than the initial
        // page. Continue through that history so its final stage/export event
        // is not hidden merely because task polling has already stopped.
        if (active || pageLength === PAGE_SIZE) {
          timer.current = window.setTimeout(() => void refresh(), pollIntervalMs);
        }
      }
    }
  }, [active, pollIntervalMs, taskId]);

  const loadMore = useCallback(async () => {
    if (pageInFlight.current) return;
    pageInFlight.current = true;
    setLoadingMore(true);
    try {
      const page = await getTaskEvents(taskId, PAGE_SIZE, events.length);
      if (mounted.current) {
        setEvents((current) => mergeEvents(current, page));
        setHasMore(page.length === PAGE_SIZE);
      }
    } catch (nextError) {
      if (mounted.current) setError(nextError);
    } finally {
      pageInFlight.current = false;
      if (mounted.current) setLoadingMore(false);
    }
  }, [events.length, loadingMore, taskId]);

  useEffect(() => {
    mounted.current = true;
    setEvents([]);
    lastEventId.current = undefined;
    setHasMore(true);
    setError(undefined);
    void refresh();
    return () => {
      mounted.current = false;
      inFlight.current = false;
      pageInFlight.current = false;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [refresh]);

  const refreshNow = useCallback(async () => {
    if (timer.current) window.clearTimeout(timer.current);
    await refresh();
  }, [refresh]);

  return {
    events,
    hasMore,
    error,
    loading,
    loadingMore,
    refreshing,
    loadMore,
    refresh: refreshNow
  };
}
