import { Alert, Button, Card, Descriptions, Space, Typography } from "antd";
import { useRef, useState } from "react";
import type { ExportFormat, TaskStatus } from "../../api/types";
import { downloadArtifact } from "../../api/tasks";
import { saveBlob } from "../../utils/download";

/** Downloads a completed artifact and shows metadata returned by public headers. */
export function ArtifactDownload({ taskId, status, format }: { taskId: string; status: TaskStatus; format?: ExportFormat | null }) {
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [sha256, setSha256] = useState<string | null>(null);
  const lock = useRef(false);
  if (status !== "completed") return null;

  async function download() {
    if (lock.current) return;
    lock.current = true;
    setLoading(true);
    setFailed(false);
    try {
      const result = await downloadArtifact(taskId);
      setSha256(result.sha256);
      saveBlob(result.blob, result.filename);
    } catch {
      setFailed(true);
    } finally {
      lock.current = false;
      setLoading(false);
    }
  }

  async function copySha256() {
    if (!sha256) return;
    try {
      await navigator.clipboard.writeText(sha256);
    } catch {
      // Clipboard availability does not affect artifact download.
    }
  }

  return <Card title="导出信息">
    {failed && <Alert role="alert" type="error" message="报告文件不可用" className="download-error" />}
    <Descriptions column={1} size="small" items={[
      { key: "format", label: "格式", children: format?.toUpperCase() ?? "未知" },
      { key: "sha", label: "SHA256", children: sha256 ? <Space wrap><Typography.Text code className="artifact-checksum">{sha256}</Typography.Text><Button size="small" onClick={() => void copySha256()}>复制 SHA256</Button></Space> : "下载后显示" }
    ]} />
    <Button type="primary" onClick={() => void download()} loading={loading} disabled={loading} aria-label={loading ? "正在下载报告" : undefined}>下载报告</Button>
  </Card>;
}
