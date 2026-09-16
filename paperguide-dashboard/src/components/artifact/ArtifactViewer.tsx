import { Button } from "antd";
import { useState } from "react";
import type { TaskStatus } from "../../api/types";
import { useArtifactViewer } from "../../hooks/useArtifactViewer";
import { saveBlob } from "../../utils/download";
import { ArtifactPreviewModal } from "./ArtifactPreviewModal";

/** Completed-task entry point for secure in-browser report previews. */
export function ArtifactViewer({ taskId, status }: { taskId: string; status: TaskStatus }) {
  const [open, setOpen] = useState(false);
  const [downloadError, setDownloadError] = useState<string>();
  const viewer = useArtifactViewer(taskId);
  if (status !== "completed") return null;

  function openViewer() {
    setOpen(true);
    setDownloadError(undefined);
    void viewer.load();
  }

  function closeViewer() {
    setOpen(false);
    setDownloadError(undefined);
    viewer.reset();
  }

  function download() {
    if (!viewer.blob || !viewer.filename) return;
    try {
      saveBlob(viewer.blob, viewer.filename);
    } catch {
      setDownloadError("报告不可用");
    }
  }

  return <>
    <Button type="primary" onClick={openViewer}>查看报告</Button>
    <ArtifactPreviewModal
      open={open}
      artifact={{ blob: viewer.blob, filename: viewer.filename, mimeType: viewer.mimeType, sha256: viewer.sha256, objectUrl: viewer.objectUrl }}
      loading={viewer.loading}
      error={downloadError ?? viewer.error}
      onClose={closeViewer}
      onDownload={download}
    />
  </>;
}
