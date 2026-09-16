import { Alert, Button, Descriptions, Modal, Space, Spin, Typography } from "antd";
import type { ArtifactViewerState } from "../../hooks/useArtifactViewer";
import { HtmlViewer } from "./HtmlViewer";
import { MarkdownViewer } from "./MarkdownViewer";
import { PdfViewer } from "./PdfViewer";

export function ArtifactPreviewModal({ open, artifact, loading, error, onClose, onDownload }: { open: boolean; artifact: ArtifactViewerState; loading: boolean; error?: string; onClose: () => void; onDownload: () => void }) {
  async function copySha256() {
    if (!artifact.sha256) return;
    try {
      await navigator.clipboard.writeText(artifact.sha256);
    } catch {
      // Clipboard availability does not affect report preview.
    }
  }

  let preview = null;
  const formatLabel = artifact.mimeType === "application/pdf"
    ? "PDF"
    : artifact.mimeType === "text/html"
      ? "HTML"
      : ["text/markdown", "text/x-markdown"].includes(artifact.mimeType ?? "")
        ? "Markdown"
        : "正在识别";
  if (artifact.blob && artifact.mimeType) {
    if (["text/markdown", "text/x-markdown"].includes(artifact.mimeType)) preview = <MarkdownViewer blob={artifact.blob} />;
    else if (artifact.mimeType === "text/html") preview = <HtmlViewer objectUrl={artifact.objectUrl} />;
    else if (artifact.mimeType === "application/pdf") preview = <PdfViewer blob={artifact.blob} mimeType={artifact.mimeType} />;
  }

  return <Modal
    title="报告预览"
    open={open}
    width="90%"
    className="artifact-preview-modal"
    closable={false}
    destroyOnHidden
    onCancel={onClose}
    footer={[
      <Button key="download" type="primary" disabled={!artifact.blob || loading} onClick={onDownload}>下载</Button>,
      <Button key="close" onClick={onClose}>关闭</Button>
    ]}
  >
    <Descriptions className="artifact-integrity" title="文件信息与完整性" column={1} size="small" items={[
      { key: "format", label: "文件格式", children: formatLabel },
      { key: "sha", label: "SHA256", children: artifact.sha256 ? <Space wrap><Typography.Text code className="artifact-checksum">{artifact.sha256}</Typography.Text><Button size="small" onClick={() => void copySha256()}>复制 SHA256</Button></Space> : "暂无" }
    ]} />
    {loading && <Spin tip="正在加载报告…"><div className="artifact-viewer-loading" /></Spin>}
    {!loading && error && <Alert role="alert" type="error" message={error} />}
    {!loading && !error && preview}
  </Modal>;
}
