import type { ExportFormat } from "../api/types";

const STORAGE_KEY = "paperguide.recentTasks";
const LEGACY_STORAGE_KEY = "paperguide.recentTasks.v1";
const MAX_TASKS = 20;

export interface RecentTaskRecord {
  taskId: string;
  createdAt: string;
  localTitle: string;
  exportFormat: ExportFormat;
}

export type RecentTask = RecentTaskRecord;

function isRecentTask(value: unknown): value is RecentTaskRecord {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<RecentTaskRecord>;
  return Boolean(
    typeof item.taskId === "string" &&
      typeof item.createdAt === "string" &&
      typeof item.localTitle === "string" &&
      item.localTitle.length <= 60 &&
      item.exportFormat &&
      ["markdown", "html", "pdf"].includes(item.exportFormat)
  );
}

export function getRecentTasks(
  storage: Storage = localStorage
): RecentTaskRecord[] {
  try {
    const raw = storage.getItem(STORAGE_KEY) ?? storage.getItem(LEGACY_STORAGE_KEY);
    const parsed: unknown = JSON.parse(raw ?? "[]");
    return Array.isArray(parsed) ? parsed.filter(isRecentTask).slice(0, MAX_TASKS) : [];
  } catch {
    return [];
  }
}

export function addRecentTask(
  task: RecentTaskRecord,
  storage: Storage = localStorage
): RecentTaskRecord[] {
  const safeTask = { ...task, localTitle: createLocalTitle(task.localTitle) };
  const tasks = [
    safeTask,
    ...getRecentTasks(storage).filter((item) => item.taskId !== safeTask.taskId)
  ].slice(0, MAX_TASKS);
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(tasks));
    storage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
    return getRecentTasks(storage);
  }
  return tasks;
}

export function removeRecentTask(
  taskId: string,
  storage: Storage = localStorage
): RecentTaskRecord[] {
  const tasks = getRecentTasks(storage).filter((item) => item.taskId !== taskId);
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(tasks));
  } catch {
    return getRecentTasks(storage);
  }
  return tasks;
}

export function clearRecentTasks(storage: Storage = localStorage): void {
  try {
    storage.removeItem(STORAGE_KEY);
    storage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
    // Unavailable storage is equivalent to an empty local history for the UI.
  }
}

export function createLocalTitle(question: string): string {
  const normalized = question.trim().replace(/\s+/g, " ");
  return normalized.length > 60 ? `${normalized.slice(0, 59)}…` : normalized;
}
