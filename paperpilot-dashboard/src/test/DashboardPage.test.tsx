import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";

const getHealth = vi.fn();
const getMetrics = vi.fn();
const getTask = vi.fn();
vi.mock("../api/runtime", () => ({
  getHealth: (...args: unknown[]) => getHealth(...args),
  getMetrics: (...args: unknown[]) => getMetrics(...args)
}));
vi.mock("../api/tasks", () => ({
  getTask: (...args: unknown[]) => getTask(...args)
}));

const ready = {
  kind: "readiness",
  status: "healthy",
  ready: true,
  checks: [{ name: "host_heartbeat", healthy: true }]
};
const metrics = {
  submitted_total: 0,
  completed_total: 0,
  failed_total: 0,
  cancelled_total: 0,
  dead_letter_total: 0,
  active_workers: 0,
  queue_size: 0,
  running_tasks: 0,
  lease_expired_total: 0,
  stale_worker_rejected_total: 0,
  average_execution_time_ms: 0
};

function renderDashboard() {
  return render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
}

describe("DashboardPage", () => {
  beforeEach(() => {
    getHealth.mockReset();
    getMetrics.mockReset();
    getTask.mockReset();
    getHealth.mockResolvedValue(ready);
    getMetrics.mockResolvedValue(metrics);
  });

  it("renders the primary dashboard regions", async () => {
    renderDashboard();
    expect(await screen.findByRole("heading", { name: "PaperPilot AI", level: 1 })).toBeTruthy();
    expect(screen.getByText("证据驱动的技术深度调研智能体")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "系统指标" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "最近调研" })).toBeTruthy();
    expect(screen.getByText("创建新的文献调研任务")).toBeTruthy();
  });

  it("navigates to New Research through the visible action", async () => {
    renderDashboard();
    const links = await screen.findAllByRole("link", { name: "新建调研" });
    await userEvent.click(links[0]);
    expect(await screen.findByRole("heading", { name: "PaperPilot 技术调研" })).toBeTruthy();
  });

  it("shows the host command without a local filesystem path", async () => {
    getHealth.mockResolvedValue({
      ...ready,
      status: "unhealthy",
      ready: false,
      checks: [{ name: "host_heartbeat", healthy: false }]
    });
    renderDashboard();
    expect(await screen.findByText("任务主机不可用")).toBeTruthy();
    expect(screen.getByText("paperpilot server start")).toBeTruthy();
    expect(document.body.textContent).not.toContain("C:\\");
  });

  it("does not expose raw runtime errors or write to console", async () => {
    const log = vi.spyOn(console, "log");
    getMetrics.mockRejectedValue(new Error("C:\\private\\runtime.sqlite3"));
    renderDashboard();
    expect(await screen.findByText("指标不可用")).toBeTruthy();
    expect(document.body.textContent).not.toContain("runtime.sqlite3");
    await waitFor(() => expect(log).not.toHaveBeenCalled());
  });
});
