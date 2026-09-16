import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { ArtifactDownload } from "../components/ArtifactDownload";

const downloadArtifact = vi.fn();
const saveBlob = vi.fn();
vi.mock("../api/tasks", () => ({ downloadArtifact: (...args: unknown[]) => downloadArtifact(...args) }));
vi.mock("../utils/download", async (importOriginal) => ({ ...await importOriginal<typeof import("../utils/download")>(), saveBlob: (...args: unknown[]) => saveBlob(...args) }));

describe("ArtifactDownload", () => {
  beforeEach(() => { downloadArtifact.mockReset(); saveBlob.mockReset(); });
  it("downloads markdown through a blob", async () => { downloadArtifact.mockResolvedValue({ blob: new Blob(["report"], { type: "text/markdown" }), filename: "report.md", contentType: "text/markdown" }); render(<ArtifactDownload taskId="task" status="completed" />); await userEvent.click(screen.getByRole("button", { name: "下载报告" })); await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), "report.md")); });
  it("downloads HTML through a blob", async () => { downloadArtifact.mockResolvedValue({ blob: new Blob(["<main />"], { type: "text/html" }), filename: "report.html", contentType: "text/html" }); render(<ArtifactDownload taskId="task" status="completed" />); await userEvent.click(screen.getByRole("button", { name: "下载报告" })); await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), "report.html")); });
  it("downloads PDF through a blob", async () => { downloadArtifact.mockResolvedValue({ blob: new Blob(["%PDF"], { type: "application/pdf" }), filename: "report.pdf", contentType: "application/pdf" }); render(<ArtifactDownload taskId="task" status="completed" />); await userEvent.click(screen.getByRole("button", { name: "下载报告" })); await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), "report.pdf")); });
  it("shows export format metadata", () => { render(<ArtifactDownload taskId="task" status="completed" format="html" />); expect(screen.getByText("导出信息")).toBeTruthy(); expect(screen.getByText("HTML")).toBeTruthy(); });
  it("shows and copies SHA256 returned by the artifact API", async () => { const sha256 = "a".repeat(64); downloadArtifact.mockResolvedValue({ blob: new Blob(["report"]), filename: "report.md", contentType: "text/markdown", sha256 }); render(<ArtifactDownload taskId="task" status="completed" format="markdown" />); await userEvent.click(screen.getByRole("button", { name: "下载报告" })); expect(await screen.findByText(sha256)).toBeTruthy(); await userEvent.click(screen.getByRole("button", { name: "复制 SHA256" })); expect(navigator.clipboard.writeText).toHaveBeenCalledWith(sha256); });
  it("shows a safe artifact error", async () => { downloadArtifact.mockRejectedValue(new ApiError("NOT_READY", "C:\\private\\report.md", "rid", 409)); render(<ArtifactDownload taskId="task" status="completed" />); await userEvent.click(screen.getByRole("button", { name: "下载报告" })); expect(await screen.findByText("报告文件不可用")).toBeTruthy(); expect(document.body.textContent).not.toContain("private"); });
  it.each(["created", "queued", "running", "cancel_requested", "cancelled", "failed", "human_review", "dead_letter"] as const)("does not render download control for %s", (status) => { render(<ArtifactDownload taskId="task" status={status} />); expect(screen.queryByRole("button", { name: "下载报告" })).toBeNull(); });
});
