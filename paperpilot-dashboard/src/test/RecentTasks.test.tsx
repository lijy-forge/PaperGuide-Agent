import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { RecentTasks } from "../components/RecentTasks";
import { addRecentTask } from "../utils/recentTasks";
import type { TaskStatus, TaskStatusResponse } from "../api/types";

const getTask = vi.fn();
vi.mock("../api/tasks", () => ({
  getTask: (...args: unknown[]) => getTask(...args)
}));

function task(taskId: string, status: TaskStatus = "running"): TaskStatusResponse {
  return {
    task_id: taskId,
    run_id: `run-${taskId}`,
    status,
    created_at: "2026-08-06T00:00:00Z",
    updated_at: "2026-08-06T00:01:00Z",
    artifact_available: false,
    artifact_format: null,
    human_review_required: false,
    retryable: false,
    error_code: null
  };
}

function remember(taskId: string, title = `Research ${taskId}`) {
  addRecentTask({
    taskId,
    createdAt: "2026-08-06T00:00:00Z",
    localTitle: title,
    exportFormat: "markdown"
  });
}

function renderRecentTasks() {
  return render(<MemoryRouter><RecentTasks /></MemoryRouter>);
}

describe("RecentTasks", () => {
  beforeEach(() => getTask.mockReset());

  it("renders an empty state from empty local storage", () => {
    renderRecentTasks();
    expect(screen.getByText("当前浏览器中暂无调研任务。")).toBeTruthy();
  });

  it("loads local records and verifies server status", async () => {
    remember("task-one", "Visual SLAM review");
    getTask.mockResolvedValue(task("task-one", "completed"));
    renderRecentTasks();
    expect(screen.getByText("Visual SLAM review")).toBeTruthy();
    expect(await screen.findByText("已完成")).toBeTruthy();
    expect(getTask).toHaveBeenCalledWith("task-one");
  });

  it("isolates Not Found and unavailable task failures", async () => {
    remember("available");
    remember("missing");
    remember("offline");
    getTask.mockImplementation((taskId: string) => {
      if (taskId === "missing") {
        return Promise.reject(new ApiError("TASK_NOT_FOUND", "missing", "id", 404));
      }
      if (taskId === "offline") return Promise.reject(new Error("network"));
      return Promise.resolve(task(taskId));
    });
    renderRecentTasks();
    expect(await screen.findByText("未找到")).toBeTruthy();
    expect(screen.getByText("不可用")).toBeTruthy();
    expect(screen.getByText("运行中")).toBeTruthy();
  });

  it("queries again only when Refresh is selected", async () => {
    remember("task-one");
    getTask.mockResolvedValue(task("task-one"));
    renderRecentTasks();
    await waitFor(() => expect(getTask).toHaveBeenCalledTimes(1));
    await userEvent.click(screen.getByRole("button", { name: /刷\s*新/ }));
    await waitFor(() => expect(getTask).toHaveBeenCalledTimes(2));
  });

  it("requires confirmation before removing a task", async () => {
    remember("task-one");
    getTask.mockResolvedValue(task("task-one"));
    renderRecentTasks();
    await screen.findByText("运行中");
    await userEvent.click(screen.getByRole("button", { name: /移\s*除/ }));
    expect(screen.getByText("Research task-one")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /确\s*认/ }));
    await waitFor(() => expect(screen.queryByText("Research task-one")).toBeNull());
  });

  it("requires confirmation before clearing all history", async () => {
    remember("task-one");
    getTask.mockResolvedValue(task("task-one"));
    renderRecentTasks();
    await screen.findByText("运行中");
    await userEvent.click(screen.getByRole("button", { name: "清除历史" }));
    expect(screen.getByText("Research task-one")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /确\s*认/ }));
    expect(await screen.findByText("当前浏览器中暂无调研任务。")).toBeTruthy();
  });

  it("links each task to its detail route and offers copy", async () => {
    remember("1234567890abcdef1234");
    getTask.mockResolvedValue(task("1234567890abcdef1234"));
    renderRecentTasks();
    const open = await screen.findByRole("link", { name: "打开" });
    expect(open.getAttribute("href")).toBe("/tasks/1234567890abcdef1234");
    expect(screen.getByRole("button", { name: "复制完整任务 ID" })).toBeTruthy();
  });

  it("renders only a public short UUID while copying the full identity", async () => {
    const id = "2517946f-a38e-42db-8bc8-1f4d00183eb6";
    remember(id, `Research ${id}`);
    getTask.mockResolvedValue(task(id));
    renderRecentTasks();
    expect(await screen.findByText("2517946f…83eb6")).toBeTruthy();
    expect(document.body.textContent ?? "").not.toContain(id);
    const copy = screen.getByRole("button", { name: "复制完整任务 ID" });
    expect(copy.getAttribute("title") ?? "").not.toContain(id);
    expect(copy.getAttribute("aria-label") ?? "").not.toContain(id);
    await userEvent.click(copy);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(id);
  });
});
