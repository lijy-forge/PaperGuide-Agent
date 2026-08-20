import { describe, expect, it } from "vitest";
import { InvalidPdfArtifactError, normalizePdfMime, validatePdfBlob } from "../components/artifact/pdfValidation";

describe("PDF artifact validation", () => {
  it("normalizes a parameterized PDF content type", () => {
    expect(normalizePdfMime("Application/PDF; charset=binary")).toBe("application/pdf");
  });

  it("accepts a non-empty PDF magic header", async () => {
    await expect(validatePdfBlob(new Blob(["%PDF-1.7 test"]), "application/pdf; charset=binary")).resolves.toBeUndefined();
  });

  it.each([
    ["", "application/pdf"],
    ["plain text", "application/pdf"],
    ["%PDF-1.7", "text/plain"],
  ])("rejects invalid artifact (%s / %s)", async (content, mime) => {
    await expect(validatePdfBlob(new Blob([content]), mime)).rejects.toBeInstanceOf(InvalidPdfArtifactError);
  });
});
