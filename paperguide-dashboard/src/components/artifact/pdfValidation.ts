export class InvalidPdfArtifactError extends Error {
  constructor() {
    super("Invalid PDF artifact.");
    this.name = "InvalidPdfArtifactError";
  }
}

export function normalizePdfMime(contentType: string | null | undefined): string {
  return (contentType ?? "").split(";", 1)[0].trim().toLowerCase();
}

export function readBlobBytes(blob: Blob): Promise<Uint8Array> {
  if (typeof blob.arrayBuffer === "function") return blob.arrayBuffer().then((buffer) => new Uint8Array(buffer));
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error ?? new Error("Unable to read PDF artifact."));
    reader.readAsArrayBuffer(blob);
  });
}

/** Validate the transport metadata and the PDF magic header before PDF.js sees bytes. */
export async function validatePdfBlob(blob: Blob, contentType: string | null | undefined): Promise<void> {
  if (normalizePdfMime(contentType) !== "application/pdf" || blob.size === 0) {
    throw new InvalidPdfArtifactError();
  }

  const header = (await readBlobBytes(blob.slice(0, 5))).subarray(0, 5);
  const magic = new TextDecoder().decode(header);
  if (magic !== "%PDF-") throw new InvalidPdfArtifactError();
}
