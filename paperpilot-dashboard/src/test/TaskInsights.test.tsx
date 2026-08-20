import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { TaskEventResponse, TaskEventType, TaskStatusResponse } from "../api/types";
import { EventStatistics } from "../components/task/EventStatistics";
import { latestProgress, TaskProgress } from "../components/task/TaskProgress";
import { calculateExecutionDuration, TaskSummary } from "../components/task/TaskSummary";
import { filterTimelineEvents, TaskTimeline } from "../components/task/TaskTimeline";

function task(status: TaskStatusResponse["status"]): TaskStatusResponse {
  return { task_id: "task-id", run_id: "run", status, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:03Z", artifact_available: false, artifact_format: null, human_review_required: false, retryable: false, error_code: null };
}

function event(id: number, event_type: TaskEventType, status: TaskEventResponse["status"], second: number): TaskEventResponse {
  return { event_id: id, event_type, status, attempt_count: 1, duration_ms: id * 10, created_at: `2026-01-01T00:00:0${second}Z` };
}

const events = [
  event(1, "task_created", "created", 0),
  event(2, "task_queued", "queued", 1),
  event(3, "lease_renewed", "running", 2),
  event(4, "task_failed", "failed", 3),
  event(5, "execution_aborted", "failed", 4),
  event(6, "task_cancelled", "cancelled", 5)
];

function renderTimeline(input = events) {
  return render(<TaskTimeline events={input} hasMore={false} loadingMore={false} onLoadMore={vi.fn()} />);
}

describe("research insight components", () => {
  it("calculates execution duration from first to last event", () => { expect(calculateExecutionDuration(events)).toBe(5_000); render(<TaskSummary task={task("completed")} events={events} />); expect(screen.getByText("5.0 秒")).toBeTruthy(); });
  it("handles an empty event summary", () => { render(<TaskSummary task={task("completed")} events={[]} />); expect(screen.getByText("0")).toBeTruthy(); expect(screen.getAllByText("暂无")).toHaveLength(3); });
  it("shows Running for an incomplete task", () => { render(<TaskSummary task={task("running")} events={events} />); expect(screen.getAllByText("运行中").length).toBeGreaterThan(0); });
  it("shows total event count", () => { render(<EventStatistics events={events} />); expect(screen.getByText("事件总数").parentElement?.textContent).toContain("6"); });
  it("classifies runtime, failure, and cancel statistics", () => { render(<EventStatistics events={events} />); expect(screen.getByText("运行事件").parentElement?.textContent).toContain("1"); expect(screen.getByText("失败事件").parentElement?.textContent).toContain("2"); expect(screen.getByText("取消事件").parentElement?.textContent).toContain("1"); });
  it("shows every event in the All filter", () => { renderTimeline(); expect(screen.getByText("任务已创建")).toBeTruthy(); expect(screen.getByText("任务失败")).toBeTruthy(); expect(screen.getByText("租约已续期")).toBeTruthy(); });
  it("filters failure events", async () => { renderTimeline(); await userEvent.click(screen.getByRole("tab", { name: "失败" })); expect(screen.getByText("任务失败")).toBeTruthy(); expect(screen.getByText("执行已中止")).toBeTruthy(); expect(screen.queryByText("任务已创建")).toBeNull(); });
  it("filters runtime events", async () => { renderTimeline(); await userEvent.click(screen.getByRole("tab", { name: "运行时" })); expect(screen.getByText("租约已续期")).toBeTruthy(); expect(screen.getByText("执行已中止")).toBeTruthy(); expect(screen.queryByText("任务失败")).toBeNull(); });
  it("orders the latest event first", () => { renderTimeline(); const text = document.body.textContent ?? ""; expect(text.indexOf("任务已取消")).toBeLessThan(text.indexOf("任务已创建")); });
  it("deduplicates event IDs", () => { expect(filterTimelineEvents([events[0], events[0]], "all")).toHaveLength(1); });
  it("expands safe event details", async () => { renderTimeline([events[0]]); await userEvent.click(screen.getByText("事件详情")); expect(screen.getByText(`事件时间：${events[0].created_at}`)).toBeTruthy(); expect(screen.getByText("状态：任务已创建")).toBeTruthy(); });
  it("copies event time", async () => { renderTimeline([events[0]]); await userEvent.click(screen.getByText("事件详情")); await userEvent.click(screen.getByRole("button", { name: "复制事件时间" })); expect(navigator.clipboard.writeText).toHaveBeenCalledWith(events[0].created_at); });
  it("calculates progress from exact lifecycle events", () => { render(<TaskProgress events={[events[0], event(7, "task_started", "running", 2), events[3]]} />); expect(screen.getAllByText("已记录")).toHaveLength(3); expect(screen.getAllByText("等待中")).toHaveLength(2); });
  it("does not invent unavailable research stages", () => { render(<TaskProgress events={events} />); expect(screen.queryByText("Retrieving Papers")).toBeNull(); expect(screen.queryByText("Reading Papers")).toBeNull(); expect(screen.queryByText("Verification")).toBeNull(); });
  it("projects persisted paper progress and partial failures", () => {
    const progress = { ...event(7, "paper_reading_progress", "running", 6), progress: { stage: "paper_reading" as const, completed: 3, total: 5, succeeded: 2, failed: 1, skipped: 0, paper_title_preview: "A public paper title", elapsed_ms: 1000, message: null } };
    render(<TaskProgress events={[progress]} startedAt="2026-01-01T00:00:00Z" />);
    expect(screen.getAllByText("阅读论文").length).toBeGreaterThan(0);
    expect(screen.getByText("3 / 5")).toBeTruthy();
    expect(screen.getByText(/2 成功 · 1 失败/)).toBeTruthy();
    expect(screen.getByText("A public paper title")).toBeTruthy();
  });
  it("uses the latest persisted progress event", () => {
    const earlier = { ...event(7, "pdf_processing_progress", "running", 6), progress: { stage: "pdf_processing" as const, completed: 1, total: 2, succeeded: 1, failed: 0, skipped: 0, paper_title_preview: null, elapsed_ms: null, message: null } };
    const later = { ...event(8, "paper_reading_progress", "running", 7), progress: { ...earlier.progress, stage: "paper_reading" as const, completed: 2, total: 2 } };
    expect(latestProgress([earlier, later])?.stage).toBe("paper_reading");
  });
  it("does not render internal runtime fields", () => { renderTimeline([{ ...events[0], host_id: "hidden-host", fencing_token: 9, lease_owner: "hidden-owner", execution_id: "hidden-execution" } as TaskEventResponse]); const page = within(document.body); expect(page.queryByText(/hidden-/)).toBeNull(); expect(document.body.textContent).not.toContain("fencing_token"); });
});
