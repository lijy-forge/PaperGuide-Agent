import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { downloadArtifact } from "../api/tasks";
import type { ArtifactResponse } from "../api/types";
import { createSafeHtmlBlob } from "../components/artifact/HtmlViewer";

export interface ArtifactViewerState {
  blob: Blob | null;
  filename: string | null;
  mimeType: string | null;
  sha256: string | null;
  objectUrl: string | null;
}

const EMPTY_ARTIFACT: ArtifactViewerState = { blob: null, filename: null, mimeType: null, sha256: null, objectUrl: null };

function normalizedMimeType(response: ArtifactResponse): string {
  return response.contentType.split(";", 1)[0].trim().toLowerCase();
}

/** Loads one report preview at a time and owns all temporary object URLs. */
export function useArtifactViewer(taskId: string) {
  const [artifact, setArtifact] = useState<ArtifactViewerState>(EMPTY_ARTIFACT);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const mounted = useRef(true);
  const inFlight = useRef(false);
  const objectUrl = useRef<string>();
  const generation = useRef(0);

  const revokeUrl = useCallback(() => {
    if (objectUrl.current) {
      URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = undefined;
    }
  }, []);

  const reset = useCallback(() => {
    generation.current += 1;
    revokeUrl();
    if (mounted.current) {
      setArtifact(EMPTY_ARTIFACT);
      setError(undefined);
      setLoading(false);
    }
  }, [revokeUrl]);

  const load = useCallback(async () => {
    if (!taskId || inFlight.current) return;
    inFlight.current = true;
    const requestGeneration = generation.current;
    setLoading(true);
    setError(undefined);
    revokeUrl();
    try {
      const response = await downloadArtifact(taskId);
      const mimeType = normalizedMimeType(response);
      if (!["text/markdown", "text/x-markdown", "text/html", "application/pdf"].includes(mimeType)) {
        throw new Error("unsupported report type");
      }
      let previewBlob = response.blob;
      if (mimeType === "text/html") {
        previewBlob = await createSafeHtmlBlob(response.blob);
      }
      // HTML needs an inert Blob URL for its sandboxed iframe. PDFs are handed
      // directly to PDF.js and must not go through the browser PDF plugin.
      const nextUrl = mimeType === "text/html" ? URL.createObjectURL(previewBlob) : null;
      if (!mounted.current || requestGeneration !== generation.current) {
        if (nextUrl) URL.revokeObjectURL(nextUrl);
        return;
      }
      if (nextUrl) objectUrl.current = nextUrl;
      setArtifact({ blob: response.blob, filename: response.filename, mimeType, sha256: response.sha256, objectUrl: nextUrl });
    } catch (nextError) {
      if (mounted.current && requestGeneration === generation.current) {
        setError(nextError instanceof ApiError && (nextError.code === "API_UNAVAILABLE" || nextError.status === undefined) ? "API 不可用" : "报告不可用");
      }
    } finally {
      inFlight.current = false;
      if (mounted.current && requestGeneration === generation.current) setLoading(false);
    }
  }, [revokeUrl, taskId]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
      revokeUrl();
    };
  }, [revokeUrl]);

  return { ...artifact, loading, error, load, reset };
}
