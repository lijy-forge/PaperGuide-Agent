import { Alert } from "antd";

function readBlobText(blob: Blob): Promise<string> {
  if (typeof blob.text === "function") return blob.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsText(blob);
  });
}

export function sanitizeHtmlReport(html: string): string {
  const document = new DOMParser().parseFromString(html, "text/html");
  document.querySelectorAll("script, iframe, object, embed, link, base, form").forEach((element) => element.remove());
  document.querySelectorAll("*").forEach((element) => {
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on") || ["src", "href", "action", "poster", "xlink:href"].includes(name)) {
        if (!attribute.value.trim().toLowerCase().startsWith("data:")) element.removeAttribute(attribute.name);
      }
      if (name === "style" && /url\s*\(|@import/i.test(attribute.value)) element.removeAttribute(attribute.name);
    }
  });
  document.querySelectorAll("style").forEach((element) => { if (/url\s*\(|@import/i.test(element.textContent ?? "")) element.remove(); });
  const policy = document.createElement("meta");
  policy.httpEquiv = "Content-Security-Policy";
  policy.content = "default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; font-src data:";
  document.head.prepend(policy);
  return `<!doctype html>${document.documentElement.outerHTML}`;
}

export async function createSafeHtmlBlob(blob: Blob): Promise<Blob> {
  return new Blob([sanitizeHtmlReport(await readBlobText(blob))], { type: "text/html" });
}

export function HtmlViewer({ objectUrl }: { objectUrl: string | null }) {
  if (!objectUrl) return <Alert role="alert" type="error" message="报告不可用" />;
  return <iframe className="artifact-frame" title="HTML 报告预览" src={objectUrl} sandbox="" referrerPolicy="no-referrer" />;
}
