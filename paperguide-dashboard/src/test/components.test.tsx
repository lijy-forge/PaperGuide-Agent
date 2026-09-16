import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MetricsResponse, TaskEventResponse, TaskStatusResponse } from "../api/types";
import { HealthIndicator } from "../components/HealthIndicator";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { ResearchProgress } from "../components/ResearchProgress";
import { RuntimeMetrics } from "../components/RuntimeMetrics";
import { taskStatusPresentation } from "../utils/taskStatus";
import { TaskStatusCard } from "../components/TaskStatusCard";
import { TaskTimeline } from "../components/TaskTimeline";

const task = (status: TaskStatusResponse["status"]): TaskStatusResponse => ({ task_id: "task", run_id: "run", status, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:01:00Z", artifact_available: status === "completed", artifact_format: status === "completed" ? "pdf" : null, human_review_required: status === "human_review", retryable: status === "failed", error_code: status === "failed" ? "TASK_FAILED" : null });
const event: TaskEventResponse = { event_id: 2, event_type: "task_started", status: "running", attempt_count: 1, duration_ms: null, created_at: "2026-01-01T00:00:00Z" };

describe("dashboard components", () => {
  it.each(["queued", "running", "completed", "failed", "dead_letter"] as const)("renders %s status with description", (status) => { render(<TaskStatusCard task={task(status)} />); expect(screen.getAllByText(taskStatusPresentation[status].label).length).toBeGreaterThan(0); });
  it("renders the event timeline newest first", () => { render(<TaskTimeline events={[event, { ...event, event_id: 1, event_type: "task_created" }]} hasMore={false} loadingMore={false} onLoadMore={vi.fn()} />); const text = document.body.textContent ?? ""; expect(text.indexOf("任务已启动")).toBeLessThan(text.indexOf("任务已创建")); });
  it("renders load more pagination control", () => { render(<TaskTimeline events={[event]} hasMore loadingMore={false} onLoadMore={vi.fn()} />); expect(screen.getByRole("button", { name: "加载更多" })).toBeTruthy(); });
  it.each([
    ["checking", "正在检查"],
    ["ready", "运行环境就绪"],
    ["host_offline", "任务主机离线"],
    ["degraded", "运行环境降级"],
    ["api_offline", "API 离线"]
  ] as const)("renders %s health with text", (state, label) => { render(<HealthIndicator state={state} />); expect(screen.getByLabelText(label)).toBeTruthy(); });
  it("renders nine public metrics", () => { const data: MetricsResponse = { submitted_total: 1, completed_total: 2, failed_total: 3, cancelled_total: 4, dead_letter_total: 5, active_workers: 6, queue_size: 7, running_tasks: 8, lease_expired_total: 9, stale_worker_rejected_total: 10, average_execution_time_ms: 1000 }; render(<RuntimeMetrics data={data} />); expect(document.querySelectorAll(".metric-card")).toHaveLength(9); expect(screen.getByText("已取消")).toBeTruthy(); expect(screen.getByText("1.0 秒")).toBeTruthy(); });
  it("does not claim fine-grained stages completed while only running", () => { render(<ResearchProgress events={[event]} status="running" />); expect(screen.getAllByText("等待中").length).toBe(4); expect(screen.queryByText("正在检索论文")).toBeNull(); });
  it("gives loading state an accessible label", () => { render(<LoadingState label="正在加载运行环境" />); expect(screen.getByLabelText("正在加载运行环境")).toBeTruthy(); });
  it("uses an alert and explicit retry label for errors", () => { render(<ErrorState message="安全错误" onRetry={vi.fn()} />); expect(screen.getByRole("alert")).toBeTruthy(); expect(screen.getByRole("button", { name: /重\s*试/ })).toBeTruthy(); });
});
