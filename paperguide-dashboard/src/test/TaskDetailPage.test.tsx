import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { TaskEventResponse, TaskStatus, TaskStatusResponse } from "../api/types";
import { TaskDetailPage } from "../pages/TaskDetailPage";
import { taskStatusPresentation } from "../utils/taskStatus";

const mocks = vi.hoisted(() => ({
  useTask: vi.fn(),
  useTaskEvents: vi.fn(),
  cancelTask: vi.fn(),
  downloadArtifact: vi.fn()
}));

vi.mock("../hooks/useTaskPolling", () => ({ useTask: (...args: unknown[]) => mocks.useTask(...args) }));
vi.mock("../hooks/useTaskEvents", () => ({ useTaskEvents: (...args: unknown[]) => mocks.useTaskEvents(...args) }));
vi.mock("../api/tasks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/tasks")>()),
  cancelTask: (...args: unknown[]) => mocks.cancelTask(...args),
  downloadArtifact: (...args: unknown[]) => mocks.downloadArtifact(...args)
}));

const refreshTask = vi.fn();
const refreshEvents = vi.fn();
const loadMore = vi.fn();
const taskId = "12345678-1234-1234-1234-123456789abc";

function task(status: TaskStatus): TaskStatusResponse {
  return {
    task_id: taskId,
    run_id: "private-run-id",
    status,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:01:00Z",
    artifact_available: status === "completed",
    artifact_format: status === "completed" ? "markdown" : null,
    human_review_required: status === "human_review",
    retryable: false,
    error_code: null
  };
}

const event: TaskEventResponse = {
  event_id: 1,
  event_type: "task_created",
  status: "created",
  attempt_count: 1,
  duration_ms: 125,
  created_at: "2026-01-01T00:00:00Z"
};

function configure(status: TaskStatus = "queued") {
  mocks.useTask.mockReturnValue({ task: task(status), error: undefined, loading: false, refresh: refreshTask });
  mocks.useTaskEvents.mockReturnValue({ events: [event], hasMore: false, error: undefined, loadingMore: false, refreshing: false, loadMore, refresh: refreshEvents });
}

function renderPage() {
  return render(<MemoryRouter initialEntries={[`/tasks/${taskId}`]}><Routes><Route path="/tasks/:taskId" element={<TaskDetailPage />} /></Routes></MemoryRouter>);
}

function LocationSearch() {
  return <span data-testid="location-search">{useLocation().search}</span>;
}

describe("TaskDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    configure();
  });

  it("loads the task detail route", () => { renderPage(); expect(screen.getByRole("heading", { name: "任务详情" })).toBeTruthy(); });
  it("passes the route task ID to useTask", () => { renderPage(); expect(mocks.useTask).toHaveBeenCalledWith(taskId); });
  it("shows an accessible loading state", () => { mocks.useTask.mockReturnValue({ task: undefined, error: undefined, loading: true, refresh: refreshTask }); renderPage(); expect(screen.getByLabelText("正在加载任务")).toBeTruthy(); });
  it("shows only a safe task error", () => { mocks.useTask.mockReturnValue({ task: undefined, error: new ApiError("FAIL", "C:\\private\\runtime.db", "rid", 500), loading: false, refresh: refreshTask }); renderPage(); expect(screen.getByText("任务操作失败。")).toBeTruthy(); expect(document.body.textContent).not.toContain("runtime.db"); });
  it("renders abbreviated task ID and a copy control", () => { renderPage(); expect(screen.getAllByText(/12345678…89abc/).length).toBeGreaterThan(0); expect(screen.getByRole("button", { name: /复\s*制/ })).toBeTruthy(); });
  it("does not expose the complete UUID through public task detail text or labels", () => {
    renderPage();
    expect(document.body.textContent ?? "").not.toContain(taskId);
    for (const node of Array.from(document.querySelectorAll("[title], [aria-label]"))) {
      expect(`${node.getAttribute("title") ?? ""}${node.getAttribute("aria-label") ?? ""}`).not.toContain(taskId);
    }
  });
  it("copies only the task ID", async () => { renderPage(); await userEvent.click(screen.getByRole("button", { name: /复\s*制/ })); expect(navigator.clipboard.writeText).toHaveBeenCalledWith(taskId); });

  it.each(["created", "queued", "running", "cancel_requested", "cancelled", "completed", "failed", "human_review", "dead_letter"] as const)("renders the %s status as text", (status) => { configure(status); renderPage(); expect(screen.getAllByText(taskStatusPresentation[status].label).length).toBeGreaterThan(0); });

  it("allows queued tasks to be cancelled", () => { configure("queued"); renderPage(); expect(screen.getByRole("button", { name: "取消任务" })).toBeTruthy(); });
  it("allows running tasks to be cancelled", () => { configure("running"); renderPage(); expect(screen.getByRole("button", { name: "取消任务" })).toBeTruthy(); });
  it.each(["created", "completed", "failed", "cancelled", "dead_letter"] as const)("does not allow %s tasks to be cancelled", (status) => { configure(status); renderPage(); expect(screen.queryByRole("button", { name: "取消任务" })).toBeNull(); });

  it("confirms cancellation and refreshes the task", async () => {
    mocks.cancelTask.mockResolvedValue(task("cancel_requested"));
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "取消任务" }));
    await userEvent.click(await screen.findByRole("button", { name: "申请取消" }));
    await waitFor(() => expect(mocks.cancelTask).toHaveBeenCalledWith(taskId));
    expect(refreshTask).toHaveBeenCalledOnce();
  });

  it("isolates cancellation failures", async () => {
    mocks.cancelTask.mockRejectedValueOnce(new ApiError("FAIL", "sqlite private path", "request-safe", 500));
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "取消任务" }));
    await userEvent.click(await screen.findByRole("button", { name: "申请取消" }));
    expect(await screen.findByText("任务操作失败。")).toBeTruthy();
    expect(document.body.textContent).not.toContain("sqlite private path");
  });

  it("polls events while the task is active", () => { renderPage(); expect(mocks.useTaskEvents).toHaveBeenCalledWith(taskId, true); });
  it("stops event polling for terminal tasks", () => { configure("failed"); renderPage(); expect(mocks.useTaskEvents).toHaveBeenCalledWith(taskId, false); });
  it("shows event type, status, time, and duration", () => { renderPage(); expect(screen.getByText("任务已创建")).toBeTruthy(); expect(screen.getByText("耗时：125 毫秒")).toBeTruthy(); expect(screen.getAllByText("已创建").length).toBeGreaterThan(0); });
  it("refreshes events only on request", async () => { renderPage(); expect(refreshEvents).not.toHaveBeenCalled(); await userEvent.click(screen.getByRole("button", { name: "刷新事件" })); expect(refreshEvents).toHaveBeenCalledOnce(); });
  it("does not render internal event fields", () => { mocks.useTaskEvents.mockReturnValue({ events: [{ ...event, host_id: "secret-host", fencing_token: 99 }], hasMore: false, error: undefined, loadingMore: false, refreshing: false, loadMore, refresh: refreshEvents }); renderPage(); expect(document.body.textContent).not.toContain("secret-host"); expect(document.body.textContent).not.toContain("fencing_token"); });
  it("shows download only for completed tasks", () => { configure("completed"); renderPage(); expect(screen.getByRole("button", { name: "下载报告" })).toBeTruthy(); });
  it("hides download for active tasks", () => { configure("running"); renderPage(); expect(screen.queryByRole("button", { name: "下载报告" })).toBeNull(); });
  it("does not render unavailable question or run ID fields", () => { mocks.useTask.mockReturnValue({ task: { ...task("queued"), question: "private research question" }, error: undefined, loading: false, refresh: refreshTask }); renderPage(); expect(document.body.textContent).not.toContain("private research question"); expect(document.body.textContent).not.toContain("private-run-id"); });
  it("removes sensitive Task Detail query parameters", async () => { render(<MemoryRouter initialEntries={[`/tasks/${taskId}?question=private&prompt=hidden&report=secret`]}><Routes><Route path="/tasks/:taskId" element={<><TaskDetailPage /><LocationSearch /></>} /></Routes></MemoryRouter>); await waitFor(() => expect(screen.getByTestId("location-search").textContent).toBe("")); expect(mocks.useTask).toHaveBeenCalledWith(taskId); });
  it("does not log sensitive task data", () => { const log = vi.spyOn(console, "log"); const error = vi.spyOn(console, "error").mockImplementation(() => undefined); renderPage(); expect(log).not.toHaveBeenCalled(); expect(error).not.toHaveBeenCalled(); });
});
