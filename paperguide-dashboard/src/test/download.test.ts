import { describe, expect, it, vi } from "vitest";
import { safeDownloadFilename, saveBlob } from "../utils/download";

describe("artifact downloads", () => {
  it("reads a markdown filename", () => expect(safeDownloadFilename('attachment; filename="report.md"', "abcdefghi")).toBe("report.md"));
  it("reads an encoded PDF filename", () => expect(safeDownloadFilename("attachment; filename*=UTF-8''paper%20report.pdf", "abc")).toBe("paper-report.pdf"));
  it("supports HTML downloads", () => expect(safeDownloadFilename('attachment; filename="report.html"', "abc")).toBe("report.html"));
  it("removes path traversal", () => expect(safeDownloadFilename('attachment; filename="../../report.pdf"', "abc")).toBe("report.pdf"));
  it("uses a safe fallback for missing filename", () => expect(safeDownloadFilename(undefined, "abcdefghi")).toBe("paperguide-report-abcdefgh.md"));
  it("rejects unsafe extensions", () => expect(safeDownloadFilename('attachment; filename="report.exe"', "abcdefghi")).toBe("paperguide-report-abcdefgh.md"));
  it("uses PDF MIME when a stale header says markdown", () => expect(safeDownloadFilename('attachment; filename="report.md"', "abcdefghi", "application/pdf")).toBe("paperguide-report-abcdefgh.pdf"));
  it("uses HTML MIME for a missing filename", () => expect(safeDownloadFilename(undefined, "abcdefghi", "text/html; charset=utf-8")).toBe("paperguide-report-abcdefgh.html"));
  it("downloads a blob without embedding HTML", () => { const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test"); const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined); const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined); saveBlob(new Blob(["<script>bad()</script>"], { type: "text/html" }), "report.html"); expect(create).toHaveBeenCalledOnce(); expect(click).toHaveBeenCalledOnce(); expect(revoke).toHaveBeenCalledWith("blob:test"); expect(document.querySelector("iframe")).toBeNull(); });
});
