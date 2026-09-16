import { Alert, Button, Card, Col, message, Modal, Row, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { cancelTask } from "../api/tasks";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { ArtifactViewer } from "../components/artifact/ArtifactViewer";
import { ArtifactDownload } from "../components/task/ArtifactDownload";
import { EventStatistics } from "../components/task/EventStatistics";
import { TaskOverview } from "../components/task/TaskOverview";
import { TaskProgress } from "../components/task/TaskProgress";
import { TaskSummary } from "../components/task/TaskSummary";
import { TaskTimeline } from "../components/task/TaskTimeline";
import { useTaskEvents } from "../hooks/useTaskEvents";
import { useTask } from "../hooks/useTaskPolling";
import { cancellableStatuses } from "../utils/taskStatus";
import { isTerminalStatus } from "../utils/taskStatus";

function RequestIdDetails({ error }: { error: unknown }) {
  if (!(error instanceof ApiError) || !error.requestId) return null;
  return <details><summary>请求 ID</summary><Typography.Text code>{error.requestId}</Typography.Text></details>;
}

export function containsSensitiveTaskQuery(search: string): boolean {
  const parameters = new URLSearchParams(search);
  return ["question", "prompt", "report"].some((name) => parameters.has(name));
}

/** Complete, browser-safe view of one research task lifecycle. */
export function TaskDetailPage() {
  const { taskId = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { task, error, loading, refresh } = useTask(taskId);
  const events = useTaskEvents(taskId, Boolean(task && !isTerminalStatus(task.status)));
  const [cancelling, setCancelling] = useState(false);
  const [operationError, setOperationError] = useState<unknown>();
  const [modal, contextHolder] = Modal.useModal();
  const [messageApi, messageHolder] = message.useMessage();

  useEffect(() => {
    if (containsSensitiveTaskQuery(location.search)) {
      navigate(location.pathname, { replace: true });
    }
  }, [location.pathname, location.search, navigate]);

  async function copyTaskId() {
    try {
      await navigator.clipboard.writeText(taskId);
      messageApi.success("任务 ID 已复制");
    } catch {
      setOperationError(new Error("clipboard unavailable"));
    }
  }

  function confirmCancel() {
    modal.confirm({
      title: "确定取消此调研任务？",
      content: "运行中的任务将在安全节点协作停止。",
      okText: "申请取消",
      cancelText: "返回",
      okButtonProps: { danger: true },
      onOk: async () => {
        setCancelling(true);
        setOperationError(undefined);
        try {
          await cancelTask(taskId);
          await refresh();
        } catch (nextError) {
          setOperationError(nextError);
        } finally {
          setCancelling(false);
        }
      }
    });
  }

  if (loading && !task) return <LoadingState label="正在加载任务" />;
  if (!task) {
    return <ErrorState message="任务操作失败。" onRetry={() => void refresh()} />;
  }

  return <div className="page-stack">
    {contextHolder}
    {messageHolder}
    <section className="task-header">
      <div>
        <Typography.Text className="eyebrow">调研任务</Typography.Text>
        <Typography.Title level={2}>任务详情</Typography.Title>
      </div>
      <Space wrap>
        {cancellableStatuses.has(task.status) && <Button danger loading={cancelling} disabled={cancelling} onClick={confirmCancel}>取消任务</Button>}
        <ArtifactViewer taskId={taskId} status={task.status} />
      </Space>
    </section>

    {Boolean(error) && <Alert role="alert" type="warning" showIcon message="任务操作失败。" description={<RequestIdDetails error={error} />} />}
    {Boolean(operationError) && <Alert role="alert" type="error" showIcon message="任务操作失败。" description={<RequestIdDetails error={operationError} />} />}

    <TaskOverview task={task} onCopyTaskId={() => void copyTaskId()} />
    <TaskSummary task={task} events={events.events} />
    <EventStatistics events={events.events} />

    <Row gutter={[16, 16]}>
      <Col xs={24} lg={14}>
        <Card title="任务事件" extra={<Button onClick={() => void events.refresh()} loading={events.refreshing}>刷新事件</Button>}>
          {Boolean(events.error) && <Alert role="alert" type="warning" message="任务操作失败。" className="section-alert" description={<RequestIdDetails error={events.error} />} />}
          <TaskTimeline events={events.events} hasMore={events.hasMore} loadingMore={events.loadingMore} onLoadMore={() => void events.loadMore()} />
        </Card>
      </Col>
      <Col xs={24} lg={10}>
        <Card title="调研进度"><TaskProgress events={events.events} startedAt={task.created_at} terminalAt={isTerminalStatus(task.status) ? task.updated_at : undefined} /></Card>
      </Col>
    </Row>
    <ArtifactDownload taskId={taskId} status={task.status} format={task.artifact_format} />
  </div>;
}
