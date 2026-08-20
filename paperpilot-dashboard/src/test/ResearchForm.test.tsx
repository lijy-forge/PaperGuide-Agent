import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { MAX_RESEARCH_QUESTION_LENGTH } from "../api/research";
import {
  isValidMaxPapers,
  MIN_RESEARCH_QUESTION_LENGTH,
  ResearchForm,
  researchSubmissionErrorMessage
} from "../components/ResearchForm";
import { NewResearchPage } from "../pages/NewResearchPage";

const mocks = vi.hoisted(() => ({ createResearch: vi.fn() }));
vi.mock("../api/research", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/research")>()),
  createResearch: (...args: unknown[]) => mocks.createResearch(...args)
}));

const accepted = {
  task_id: "task-id",
  status: "queued",
  created_at: "2026-01-01T00:00:00Z"
};
const validQuestion = "Evidence research question";

function renderForm(onSubmitted = vi.fn()) {
  render(<ResearchForm onSubmitted={onSubmitted} />);
  return onSubmitted;
}

async function enterQuestion(value = validQuestion) {
  await userEvent.type(
    screen.getByRole("textbox", { name: "调研问题" }),
    value
  );
}

async function submit() {
  await userEvent.click(screen.getByRole("button", { name: "开始调研" }));
}

describe("NewResearchPage", () => {
  beforeEach(() => mocks.createResearch.mockReset());

  it("renders the requested page title and subtitle", () => {
    render(<MemoryRouter><NewResearchPage /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "PaperPilot 技术调研" })).toBeTruthy();
    expect(
      screen.getByText("创建一个以证据为基础的技术文献调研任务。")
    ).toBeTruthy();
  });

  it("navigates only to the returned task ID", async () => {
    mocks.createResearch.mockResolvedValue({ ...accepted, task_id: "safe-task-id" });
    render(
      <MemoryRouter initialEntries={["/research/new"]}>
        <Routes>
          <Route path="/research/new" element={<NewResearchPage />} />
          <Route path="/tasks/:taskId" element={<div>任务目标页面</div>} />
        </Routes>
      </MemoryRouter>
    );
    await enterQuestion("Private evidence research question");
    await submit();
    expect(await screen.findByText("任务目标页面")).toBeTruthy();
  });
});

describe("ResearchForm", () => {
  beforeEach(() => mocks.createResearch.mockReset());

  it("rejects an empty or whitespace-only question", async () => {
    renderForm();
    await userEvent.type(
      screen.getByRole("textbox", { name: "调研问题" }),
      "   "
    );
    await submit();
    expect(await screen.findByText("请输入调研问题。")).toBeTruthy();
    expect(mocks.createResearch).not.toHaveBeenCalled();
  });

  it("enforces minimum and API maximum question lengths", async () => {
    renderForm();
    const input = screen.getByRole("textbox", { name: "调研问题" });
    expect(input.getAttribute("maxlength")).toBe(
      String(MAX_RESEARCH_QUESTION_LENGTH)
    );
    expect(screen.getByText(`0 / ${MAX_RESEARCH_QUESTION_LENGTH}`)).toBeTruthy();
    await userEvent.type(input, "x".repeat(MIN_RESEARCH_QUESTION_LENGTH - 1));
    await submit();
    expect(
      await screen.findByText(
        `调研问题至少需要 ${MIN_RESEARCH_QUESTION_LENGTH} 个字符。`
      )
    ).toBeTruthy();
  });

  it("defaults Maximum Papers to ten", () => {
    renderForm();
    expect(
      (screen.getByRole("spinbutton", { name: "最大论文数量" }) as HTMLInputElement)
        .value
    ).toBe("10");
  });

  it("validates Maximum Papers between one and fifty", () => {
    expect(isValidMaxPapers(0)).toBe(false);
    expect(isValidMaxPapers(1)).toBe(true);
    expect(isValidMaxPapers(50)).toBe(true);
    expect(isValidMaxPapers(51)).toBe(false);
  });

  it("defaults Export Format to Markdown", () => {
    renderForm();
    expect(
      (screen.getByRole("radio", { name: "Markdown" }) as HTMLInputElement)
        .checked
    ).toBe(true);
  });

  it("allows changing Export Format", async () => {
    renderForm();
    fireEvent.click(screen.getByRole("radio", { name: "HTML" }));
    expect(
      (screen.getByRole("radio", { name: "HTML" }) as HTMLInputElement).checked
    ).toBe(true);
  });

  it("trims the question and calls createResearch", async () => {
    mocks.createResearch.mockResolvedValue(accepted);
    renderForm();
    await enterQuestion(`  ${validQuestion}  `);
    await submit();
    await waitFor(() => expect(mocks.createResearch).toHaveBeenCalledOnce());
    expect(mocks.createResearch.mock.calls[0][0]).toMatchObject({
      question: validQuestion,
      max_papers: 10,
      export_format: "markdown"
    });
  });

  it("stores only bounded RecentTask metadata", async () => {
    mocks.createResearch.mockResolvedValue(accepted);
    renderForm();
    const question = `${"a".repeat(70)} UNIQUE_PRIVATE_TAIL`;
    await enterQuestion(question);
    await submit();
    await waitFor(() => expect(mocks.createResearch).toHaveBeenCalledOnce());
    const stored = localStorage.getItem("paperpilot.recentTasks") ?? "";
    expect(stored).toContain("task-id");
    expect(stored).not.toContain("UNIQUE_PRIVATE_TAIL");
    expect(stored).not.toContain("artifact");
    expect(stored).not.toContain("evidence");
  });

  it("passes the task ID to the navigation callback", async () => {
    mocks.createResearch.mockResolvedValue(accepted);
    const submitted = renderForm();
    await enterQuestion();
    await submit();
    await waitFor(() => expect(submitted).toHaveBeenCalledWith("task-id"));
  });

  it("submits and navigates under React StrictMode", async () => {
    mocks.createResearch.mockResolvedValue(accepted);
    const submitted = vi.fn();
    render(
      <StrictMode>
        <ResearchForm onSubmitted={submitted} />
      </StrictMode>
    );
    await enterQuestion();
    await submit();
    await waitFor(() => expect(submitted).toHaveBeenCalledWith("task-id"));
    expect(
      screen.getByRole("button", { name: "开始调研" }).hasAttribute("disabled")
    ).toBe(false);
  });

  it("uses an in-flight lock to prevent duplicate requests", async () => {
    let resolveRequest: ((value: typeof accepted) => void) | undefined;
    mocks.createResearch.mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      })
    );
    const submitted = renderForm();
    await enterQuestion();
    const button = screen.getByRole("button", { name: "开始调研" });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(mocks.createResearch).toHaveBeenCalledOnce());
    resolveRequest?.(accepted);
    await waitFor(() => expect(submitted).toHaveBeenCalledOnce());
  });

  it("maps a 422 response to Invalid request and supports retry", async () => {
    mocks.createResearch
      .mockRejectedValueOnce(new ApiError("INVALID_REQUEST", "private", "rid", 422))
      .mockResolvedValueOnce(accepted);
    const submitted = renderForm();
    await enterQuestion();
    await submit();
    expect(await screen.findByText(/请求无效/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /重\s*试/ }));
    await waitFor(() => expect(submitted).toHaveBeenCalledWith("task-id"));
  });

  it("maps Host unavailability to a safe startup instruction", async () => {
    mocks.createResearch.mockRejectedValueOnce(
      new ApiError("TASK_HOST_UNAVAILABLE", "private path", "rid", 503)
    );
    renderForm();
    await enterQuestion();
    await submit();
    expect(await screen.findByText("任务主机不可用。")).toBeTruthy();
    expect(screen.getByText("paperpilot server start")).toBeTruthy();
    expect(document.body.textContent).not.toContain("private path");
  });

  it("maps network errors to API unavailable", async () => {
    mocks.createResearch.mockRejectedValueOnce(
      new ApiError("API_UNAVAILABLE", "socket detail", undefined, undefined)
    );
    renderForm();
    await enterQuestion();
    await submit();
    expect(await screen.findByText("PaperPilot API 不可用。")).toBeTruthy();
    expect(document.body.textContent).not.toContain("socket detail");
  });

  it("uses a generic safe message for other failures", () => {
    expect(researchSubmissionErrorMessage(new Error("sqlite path"))).toBe(
      "创建调研任务失败。"
    );
  });

  it("supports Ctrl+Enter submission", async () => {
    mocks.createResearch.mockResolvedValue(accepted);
    renderForm();
    const input = screen.getByRole("textbox", { name: "调研问题" });
    await userEvent.type(input, validQuestion);
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(mocks.createResearch).toHaveBeenCalledOnce());
  });

  it("does not print the question or errors to console", async () => {
    const spies = [
      vi.spyOn(console, "log"),
      vi.spyOn(console, "info"),
      vi.spyOn(console, "warn"),
      vi.spyOn(console, "error")
    ];
    mocks.createResearch.mockResolvedValue(accepted);
    renderForm();
    await enterQuestion("Private research content");
    await submit();
    await waitFor(() => expect(mocks.createResearch).toHaveBeenCalledOnce());
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });
});
