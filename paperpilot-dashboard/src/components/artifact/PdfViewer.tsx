import { Alert, Button, Space, Spin, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist/build/pdf.mjs";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { InvalidPdfArtifactError, readBlobBytes, validatePdfBlob } from "./pdfValidation";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

const MIN_SCALE = 0.5;
const MAX_SCALE = 2;
const SCALE_STEP = 0.1;

type PdfViewerProps = { blob: Blob | null; mimeType?: string | null };

function isCancellation(error: unknown): boolean {
  return error instanceof Error && (error.name === "RenderingCancelledException" || error.name === "AbortException");
}

/** Canvas-only PDF.js viewer. It deliberately does not use the browser PDF plugin. */
export function PdfViewer({ blob, mimeType }: PdfViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const documentRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);
  const loadingTaskRef = useRef<pdfjsLib.PDFDocumentLoadingTask | null>(null);
  const renderTaskRef = useRef<pdfjsLib.RenderTask | null>(null);
  const generationRef = useRef(0);
  const renderSequenceRef = useRef(0);
  const lastContainerWidthRef = useRef(0);
  const [loading, setLoading] = useState(true);
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState<string>();
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [scale, setScale] = useState(1);
  const [fitWidth, setFitWidth] = useState(true);
  const [containerWidth, setContainerWidth] = useState(0);

  const cancelRender = useCallback(() => {
    renderSequenceRef.current += 1;
    renderTaskRef.current?.cancel();
    renderTaskRef.current = null;
  }, []);

  const destroyDocument = useCallback(() => {
    cancelRender();
    void loadingTaskRef.current?.destroy();
    loadingTaskRef.current = null;
    void documentRef.current?.destroy();
    documentRef.current = null;
    const canvas = canvasRef.current;
    if (canvas) {
      canvas.width = 0;
      canvas.height = 0;
    }
  }, [cancelRender]);

  const renderPage = useCallback(async (pageNumber: number, requestedScale: number, generation: number) => {
    const document = documentRef.current;
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!document || !canvas || !container || generation !== generationRef.current) return;
    cancelRender();
    const renderSequence = renderSequenceRef.current;
    setRendering(true);
    setError(undefined);
    try {
      const page = await document.getPage(pageNumber);
      if (generation !== generationRef.current || renderSequence !== renderSequenceRef.current) return;
      const unscaled = page.getViewport({ scale: 1 });
      const effectiveScale = fitWidth ? Math.min(MAX_SCALE, Math.max(MIN_SCALE, (container.clientWidth - 24) / unscaled.width)) : requestedScale;
      if (fitWidth) setScale((value) => Math.abs(value - effectiveScale) < 0.01 ? value : effectiveScale);
      const dpr = Math.max(1, window.devicePixelRatio || 1);
      const viewport = page.getViewport({ scale: effectiveScale });
      canvas.width = Math.ceil(viewport.width * dpr);
      canvas.height = Math.ceil(viewport.height * dpr);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("canvas unavailable");
      if (generation !== generationRef.current || renderSequence !== renderSequenceRef.current) return;
      const renderTask = page.render({ canvasContext: context, viewport, transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0] });
      renderTaskRef.current = renderTask;
      await renderTask.promise;
      if (generation !== generationRef.current || renderSequence !== renderSequenceRef.current) return;
    } catch (renderError) {
      if (!isCancellation(renderError) && generation === generationRef.current && renderSequence === renderSequenceRef.current) {
        setError("Unable to render PDF page.");
      }
    } finally {
      if (generation === generationRef.current && renderSequence === renderSequenceRef.current) {
        setRendering(false);
        renderTaskRef.current = null;
      }
    }
  }, [cancelRender, fitWidth]);

  useEffect(() => {
    const generation = ++generationRef.current;
    destroyDocument();
    setLoading(true);
    setError(undefined);
    setCurrentPage(1);
    setTotalPages(0);
    if (!blob) {
      setLoading(false);
      setError("Invalid PDF artifact.");
      return () => undefined;
    }
    let active = true;
    void (async () => {
      try {
        await validatePdfBlob(blob, mimeType);
        const data = await readBlobBytes(blob);
        const loadingTask = pdfjsLib.getDocument({ data });
        loadingTaskRef.current = loadingTask;
        const document = await loadingTask.promise;
        if (!active || generation !== generationRef.current) {
          await document.destroy();
          return;
        }
        documentRef.current = document;
        setTotalPages(document.numPages);
        setLoading(false);
      } catch (loadError) {
        if (!active || generation !== generationRef.current) return;
        setLoading(false);
        const invalid = loadError instanceof InvalidPdfArtifactError || (loadError instanceof Error && loadError.name === "InvalidPdfArtifactError");
        setError(invalid ? "Invalid PDF artifact." : "Unable to load PDF report.");
      }
    })();
    return () => {
      active = false;
      generationRef.current += 1;
      destroyDocument();
    };
  // The document lifecycle is tied to the artifact, not to page/zoom controls.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blob, mimeType, destroyDocument]);

  useEffect(() => {
    if (!documentRef.current || loading) return;
    void renderPage(currentPage, scale, generationRef.current);
  }, [containerWidth, currentPage, scale, fitWidth, loading, renderPage]);

  useEffect(() => {
    if (!fitWidth || !containerRef.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const width = Math.round(entries[0]?.contentRect.width ?? 0);
      if (width > 0 && Math.abs(width - lastContainerWidthRef.current) > 1) {
        lastContainerWidthRef.current = width;
        setContainerWidth(width);
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [fitWidth]);

  if (error) return <Alert role="alert" type="error" message={error} />;
  return <div className="pdf-viewer" aria-label="PDF report viewer">
    <Space className="pdf-toolbar" wrap>
      <Button aria-label="Previous page" onClick={() => setCurrentPage((page) => Math.max(1, page - 1))} disabled={loading || currentPage <= 1}>Previous</Button>
      <Typography.Text aria-live="polite">Page {currentPage} of {totalPages || "—"}</Typography.Text>
      <Button aria-label="Next page" onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))} disabled={loading || currentPage >= totalPages}>Next</Button>
      <Button aria-label="Zoom out" onClick={() => { setFitWidth(false); setScale((value) => Math.max(MIN_SCALE, +(value - SCALE_STEP).toFixed(2))); }} disabled={loading}>−</Button>
      <Typography.Text>{Math.round(scale * 100)}%</Typography.Text>
      <Button aria-label="Zoom in" onClick={() => { setFitWidth(false); setScale((value) => Math.min(MAX_SCALE, +(value + SCALE_STEP).toFixed(2))); }} disabled={loading}>+</Button>
      <Button aria-label="Fit page width" onClick={() => setFitWidth(true)} disabled={loading}>Fit Width</Button>
    </Space>
    <div ref={containerRef} className="pdf-canvas-wrap">
      {loading && <div className="pdf-loading" aria-live="polite"><Spin tip="Loading PDF report..." /></div>}
      {!loading && rendering && <div className="pdf-rendering" aria-live="polite">Rendering page...</div>}
      <canvas ref={canvasRef} className="pdf-canvas" aria-label={`PDF page ${currentPage}`} />
    </div>
  </div>;
}
