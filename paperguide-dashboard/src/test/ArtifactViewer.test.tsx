import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { ArtifactViewer } from "../components/artifact/ArtifactViewer";
import { sanitizeHtmlReport } from "../components/artifact/HtmlViewer";
import { MarkdownViewer } from "../components/artifact/MarkdownViewer";

const mocks = vi.hoisted(() => ({ downloadArtifact: vi.fn(), saveBlob: vi.fn() }));
vi.mock("../api/tasks", () => ({ downloadArtifact: (...args: unknown[]) => mocks.downloadArtifact(...args) }));
vi.mock("../utils/download", async (importOriginal) => ({ ...(await importOriginal<typeof import("../utils/download")>()), saveBlob: (...args: unknown[]) => mocks.saveBlob(...args) }));

function response(content: string, contentType: string, filename = "report.md", sha256: string | null = null) {
  return { blob: new Blob([content], { type: contentType }), filename, contentType, sha256 };
}

async function openViewer() {
  await userEvent.click(screen.getByRole("button", { name: "查看报告" }));
}

describe("ArtifactViewer", () => {
  beforeEach(() => {
    mocks.downloadArtifact.mockReset();
    mocks.saveBlob.mockReset();
    vi.mocked(URL.createObjectURL).mockReturnValue("blob:artifact-preview");
  });

  it("shows View Report for completed tasks", () => { render(<ArtifactViewer taskId="task" status="completed" />); expect(screen.getByRole("button", { name: "查看报告" })).toBeTruthy(); });
  it.each(["created", "queued", "running", "cancel_requested", "cancelled", "failed", "human_review", "dead_letter"] as const)("hides View Report for %s tasks", (status) => { render(<ArtifactViewer taskId="task" status={status} />); expect(screen.queryByRole("button", { name: "查看报告" })).toBeNull(); });

  it("renders safe Markdown structures", async () => {
    mocks.downloadArtifact.mockResolvedValue(response("# Report\n\n- One\n- Two\n\n> Evidence\n\n```ts\nconst value = 1;\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |", "text/markdown"));
    render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    expect(await screen.findByRole("heading", { name: "Report" })).toBeTruthy();
    expect(screen.getByText("One")).toBeTruthy();
    expect(screen.getByText("Evidence")).toBeTruthy();
    expect(screen.getByText("const value = 1;")).toBeTruthy();
    expect(screen.getByText("A")).toBeTruthy();
  });

  it("finishes loading Markdown under React StrictMode", async () => {
    mocks.downloadArtifact.mockResolvedValue(
      response("# Strict Report", "text/markdown", "report.md", "a".repeat(64))
    );
    render(
      <StrictMode>
        <ArtifactViewer taskId="task" status="completed" />
      </StrictMode>
    );

    await openViewer();

    expect(await screen.findByRole("heading", { name: "Strict Report" })).toBeTruthy();
    expect(screen.queryByText("正在加载报告…")).toBeNull();
    expect(screen.getByText("a".repeat(64))).toBeTruthy();
  });

  it("renders raw HTML as inert Markdown text", async () => {
    mocks.downloadArtifact.mockResolvedValue(response("<script>window.reportExecuted = true</script>", "text/markdown"));
    render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    expect(await screen.findByText(/window.reportExecuted/)).toBeTruthy();
    expect(document.querySelector("script")).toBeNull();
    expect((window as unknown as { reportExecuted?: boolean }).reportExecuted).toBeUndefined();
  });

  it("isolates malformed Markdown read failures", async () => {
    const brokenBlob = { text: () => Promise.reject(new Error("private parser detail")) } as Blob;
    render(<MarkdownViewer blob={brokenBlob} />);
    expect(await screen.findByText("无法渲染报告。")).toBeTruthy();
    expect(document.body.textContent).not.toContain("private parser detail");
  });

  it("shows loading while the report request is pending", async () => {
    mocks.downloadArtifact.mockReturnValue(new Promise(() => undefined));
    render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    expect(screen.getByText("正在加载报告…")).toBeTruthy();
  });

  it("shows a safe report error", async () => {
    mocks.downloadArtifact.mockRejectedValueOnce(new ApiError("FAILED", "C:\\private\\report.md", "rid", 500));
    render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    expect(await screen.findByText("报告不可用")).toBeTruthy();
    expect(document.body.textContent).not.toContain("private");
  });

  it("distinguishes API network failure", async () => {
    mocks.downloadArtifact.mockRejectedValueOnce(new ApiError("API_UNAVAILABLE", "socket detail", undefined, undefined));
    render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    expect(await screen.findByText("API 不可用")).toBeTruthy();
    expect(document.body.textContent).not.toContain("socket detail");
  });

  it("uses an empty sandbox and Blob URL for HTML", async () => {
    mocks.downloadArtifact.mockResolvedValue(response("<h1>HTML Report</h1>", "text/html", "report.html"));
    render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    const frame = await screen.findByTitle("HTML 报告预览");
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.getAttribute("src")).toBe("blob:artifact-preview");
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
  });

  it("strips scripts and external-resource attributes from HTML previews", () => {
    const safe = sanitizeHtmlReport('<script>bad()</script><img src="https://tracker.example/x"><a href="https://example.com">link</a><iframe src="https://example.com"></iframe>');
    expect(safe).not.toContain("<script");
    expect(safe).not.toContain("<iframe");
    expect(safe).not.toContain("https://");
    expect(safe).toContain("Content-Security-Policy");
  });

  it("revokes the HTML URL when the viewer closes", async () => {
    mocks.downloadArtifact.mockResolvedValue(response("<p>Safe</p>", "text/html", "report.html"));
    render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    await screen.findByTitle("HTML 报告预览");
    await userEvent.click(screen.getByRole("button", { name: /关\s*闭/ }));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:artifact-preview");
  });

  it("rejects an invalid PDF artifact before browser plugins can run", async () => {
    mocks.downloadArtifact.mockResolvedValue(response("not a pdf", "application/pdf", "report.pdf"));
    render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(document.querySelector("iframe, object, embed")).toBeNull();
  });

  it("shows a safe error when original download saving fails", async () => {
    mocks.downloadArtifact.mockResolvedValue(response("not a pdf", "application/pdf", "report.pdf"));
    mocks.saveBlob.mockImplementationOnce(() => { throw new Error("private path"); });
    render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    await screen.findByRole("alert");
    await userEvent.click(screen.getByRole("button", { name: /下\s*载/ }));
    expect(await screen.findByText("报告不可用")).toBeTruthy();
    expect(document.body.textContent).not.toContain("private path");
  });

  it("does not persist report content or add it to the URL", async () => {
    const report = "UNIQUE_PRIVATE_REPORT_CONTENT";
    mocks.downloadArtifact.mockResolvedValue(response(report, "text/markdown"));
    render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    await screen.findByText(report);
    expect(JSON.stringify(localStorage)).not.toContain(report);
    expect(window.location.href).not.toContain(report);
  });

  it("shows Not available when SHA256 is absent", async () => {
    mocks.downloadArtifact.mockResolvedValue(response("report", "text/markdown"));
    render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    await screen.findByText("report");
    expect(screen.getByText("暂无")).toBeTruthy();
  });

  it("shows and copies SHA256", async () => {
    const sha256 = "b".repeat(64);
    mocks.downloadArtifact.mockResolvedValue(response("report", "text/markdown", "report.md", sha256));
    render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    expect(await screen.findByText(sha256)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "复制 SHA256" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(sha256);
  });

  it("shows the actual PDF format returned by the artifact API", async () => {
    mocks.downloadArtifact.mockResolvedValue(response("not a pdf", "application/pdf", "research-report.pdf"));
    render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    expect(await screen.findByText("PDF")).toBeTruthy();
    expect(screen.getByText("文件格式")).toBeTruthy();
  });

  it("prevents duplicate report downloads", async () => {
    mocks.downloadArtifact.mockReturnValue(new Promise(() => undefined));
    render(<ArtifactViewer taskId="task" status="completed" />);
    const button = screen.getByRole("button", { name: "查看报告" });
    await userEvent.click(button);
    await userEvent.click(button);
    expect(mocks.downloadArtifact).toHaveBeenCalledOnce();
  });

  it("does not create a Blob URL for PDF.js previews", async () => {
    mocks.downloadArtifact.mockResolvedValue(response("not a pdf", "application/pdf", "report.pdf"));
    const view = render(<ArtifactViewer taskId="task" status="completed" />);
    await openViewer();
    await screen.findByRole("alert");
    view.unmount();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
