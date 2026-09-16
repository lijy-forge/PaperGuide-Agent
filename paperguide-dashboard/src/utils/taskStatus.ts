import type { TaskStatus } from "../api/types";

export const terminalStatuses = new Set<TaskStatus>(["cancelled", "completed", "failed", "human_review", "dead_letter"]);
export const cancellableStatuses = new Set<TaskStatus>(["queued", "running"]);

export interface StatusPresentation {
  label: string;
  color: string;
  description: string;
}

export const taskStatusPresentation: Record<TaskStatus, StatusPresentation> = {
  created: { label: "已创建", color: "default", description: "系统已接受该请求。" },
  queued: { label: "排队中", color: "processing", description: "正在等待可用的工作线程。" },
  running: { label: "运行中", color: "blue", description: "调研工作流正在执行。" },
  cancel_requested: { label: "已申请取消", color: "warning", description: "正在等待当前任务安全停止。" },
  cancelled: { label: "已取消", color: "default", description: "调研任务已取消。" },
  completed: { label: "已完成", color: "success", description: "调研报告已生成。" },
  failed: { label: "失败", color: "error", description: "任务执行失败，可以重试。" },
  dead_letter: { label: "死信任务", color: "error", description: "任务已达到最大重试次数。" },
  human_review: { label: "等待人工审核", color: "warning", description: "该任务需要人工核验。" }
};

export function getTaskStatusLabel(status: TaskStatus): string {
  return taskStatusPresentation[status].label;
}

export function getTaskStatusDescription(status: TaskStatus): string {
  return taskStatusPresentation[status].description;
}

export function isTerminalStatus(status: TaskStatus | undefined): boolean {
  return status ? terminalStatuses.has(status) : false;
}

/** Backwards-compatible alias used by existing dashboard code. */
export const isTerminal = isTerminalStatus;
