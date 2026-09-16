/**
 * Returns the task identifier safe for public UI display.
 *
 * The full value remains the routing and copy identity, but is never rendered
 * in visible text or accessibility metadata.
 */
export function formatPublicTaskId(taskId: string | null | undefined): string {
  if (typeof taskId !== "string" || taskId.length === 0) return "任务未标识";
  return taskId.length > 13 ? `${taskId.slice(0, 8)}…${taskId.slice(-5)}` : taskId;
}
