const SAFE_EXTENSION = /\.(md|markdown|html|pdf)$/i;

function extensionForContentType(contentType: string | undefined): ".md" | ".html" | ".pdf" | null {
  const mime = contentType?.split(";", 1)[0].trim().toLowerCase();
  if (mime === "application/pdf") return ".pdf";
  if (mime === "text/html") return ".html";
  if (mime === "text/markdown" || mime === "text/x-markdown") return ".md";
  return null;
}

export function safeDownloadFilename(contentDisposition: string | undefined, taskId: string, contentType?: string): string {
  const expectedExtension = extensionForContentType(contentType);
  const encoded = contentDisposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const plain = contentDisposition?.match(/filename="?([^";]+)"?/i)?.[1];
  let candidate = encoded ? decodeURIComponent(encoded) : plain;
  candidate = candidate?.split(/[\\/]/).pop()?.replace(/[^a-zA-Z0-9._-]/g, "-");
  if (!candidate || candidate.startsWith(".") || !SAFE_EXTENSION.test(candidate) || (expectedExtension !== null && !candidate.toLowerCase().endsWith(expectedExtension))) {
    return `paperpilot-report-${taskId.slice(0, 8)}${expectedExtension ?? ".md"}`;
  }
  return candidate;
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  anchor.click();
  URL.revokeObjectURL(url);
}
