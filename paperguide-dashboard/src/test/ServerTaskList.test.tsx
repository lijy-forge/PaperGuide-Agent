import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ServerTaskList } from "../components/ServerTaskList";
import type { TaskStatus, TaskStatusResponse } from "../api/types";

const listTasks = vi.fn();
vi.mock("../api/tasks", () => ({
  listTasks: (...args: unknown[]) => listTasks(...args)
}));

function task(taskId: string, status: TaskStatus = "failed"): TaskStatusResponse {
  return {
    task_id: taskId,
    run_id: `run-${taskId}`,
    status,
    created_at: "2026-09-18T00:00:00Z",
    updated_at: "2026-09-18T00:01:00Z",
    artifact_available: false,
    artifact_format: null,
    human_review_required: false,
    retryable: status === "failed",
    error_code: status === "failed" ? "TASK_FAILED" : null
  };
}

function page(items: TaskStatusResponse[], total = items.length, offset = 0) {
  return { items, total, limit: 10, offset };
}

describe("ServerTaskList", () => {
  beforeEach(() => {
    listTasks.mockReset();
  });

  it("lists tasks the browser never submitted", async () => {
    listTasks.mockResolvedValue(page([task("11111111-1111-1111-1111-111111111111")]));

    render(
      <MemoryRouter>
        <ServerTaskList />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText("失败")).toBeTruthy());
    expect(screen.getByText("TASK_FAILED")).toBeTruthy();
  });

  it("asks the server for one status when filtered", async () => {
    listTasks.mockResolvedValue(page([]));

    render(
      <MemoryRouter>
        <ServerTaskList status="dead_letter" />
      </MemoryRouter>
    );

    await waitFor(() =>
      expect(listTasks).toHaveBeenCalledWith(
        expect.objectContaining({ status: "dead_letter" })
      )
    );
  });

  it("sends no status for the all filter, rather than the literal 'all'", async () => {
    listTasks.mockResolvedValue(page([]));

    render(
      <MemoryRouter>
        <ServerTaskList status="all" />
      </MemoryRouter>
    );

    await waitFor(() => expect(listTasks).toHaveBeenCalled());
    expect(listTasks.mock.calls[0][0].status).toBeUndefined();
  });

  it("pages forward and back", async () => {
    listTasks.mockResolvedValue(
      page([task("22222222-2222-2222-2222-222222222222")], 25)
    );

    render(
      <MemoryRouter>
        <ServerTaskList />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText("下一页")).toBeTruthy());
    await userEvent.click(screen.getByText("下一页"));

    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 10 })
      )
    );
  });

  it("returns to the first page when the filter changes", async () => {
    listTasks.mockResolvedValue(
      page([task("33333333-3333-3333-3333-333333333333")], 25)
    );

    const { rerender } = render(
      <MemoryRouter>
        <ServerTaskList status="all" />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText("下一页")).toBeTruthy());
    await userEvent.click(screen.getByText("下一页"));
    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 }))
    );

    // Without the reset this would request page two of a filter that may only
    // have one page, and the list would come back empty for no visible reason.
    rerender(
      <MemoryRouter>
        <ServerTaskList status="failed" />
      </MemoryRouter>
    );

    await waitFor(() =>
      expect(listTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "failed", offset: 0 })
      )
    );
  });

  it("reports a failure instead of showing an empty list", async () => {
    listTasks.mockRejectedValue(new Error("network down"));

    render(
      <MemoryRouter>
        <ServerTaskList />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  });
});
