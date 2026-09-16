import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pdfMocks = vi.hoisted(() => ({
  getDocument: vi.fn(),
  getPage: vi.fn()
}));

vi.mock("pdfjs-dist/build/pdf.mjs", () => ({
  GlobalWorkerOptions: { workerSrc: "" },
  getDocument: (...args: unknown[]) => pdfMocks.getDocument(...args)
}));
vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({ default: "/pdf.worker.js" }));

import { PdfViewer } from "../components/artifact/PdfViewer";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

function page() {
  return {
    getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }),
    render: vi.fn(() => ({ promise: Promise.resolve(), cancel: vi.fn() }))
  };
}

describe("PdfViewer", () => {
  beforeEach(() => {
    pdfMocks.getDocument.mockReset();
    pdfMocks.getPage.mockReset();
  });

  it("ignores an obsolete page render when navigation overtakes getPage", async () => {
    const firstPage = deferred<ReturnType<typeof page>>();
    const secondPage = deferred<ReturnType<typeof page>>();
    pdfMocks.getPage.mockImplementation((pageNumber: number) => pageNumber === 1 ? firstPage.promise : secondPage.promise);
    const document = { numPages: 2, getPage: pdfMocks.getPage, destroy: vi.fn().mockResolvedValue(undefined) };
    pdfMocks.getDocument.mockReturnValue({ promise: Promise.resolve(document), destroy: vi.fn().mockResolvedValue(undefined) });

    const blob = new Blob([new TextEncoder().encode("%PDF-1.7\nfixture")], { type: "application/pdf" });
    render(<PdfViewer blob={blob} mimeType="application/pdf" />);

    const next = await screen.findByRole("button", { name: "Next page" });
    await waitFor(() => expect(next.hasAttribute("disabled")).toBe(false));
    fireEvent.click(next);
    await act(async () => {
      firstPage.resolve(page());
      secondPage.resolve(page());
      await Promise.resolve();
    });

    await waitFor(() => expect(screen.getByText("Page 2 of 2")).toBeTruthy());
    expect(screen.queryByText("Unable to render PDF page.")).toBeNull();
  });
});
