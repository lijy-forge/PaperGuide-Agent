import { Alert, Button, Card, Descriptions, Space, Typography } from "antd";
import type { TaskStatusResponse } from "../../api/types";
import { formatDate } from "../../utils/date";
import { formatPublicTaskId } from "../../utils/taskId";
import { getTaskStatusDescription } from "../../utils/taskStatus";
import { explainFailure } from "../../utils/taskFailure";
import { TaskStatusTag } from "./TaskStatusTag";

/** Public, browser-safe overview of a research task. */
export function TaskOverview({ task, onCopyTaskId }: { task: TaskStatusResponse; onCopyTaskId?: () => void }) {
  const failure = explainFailure(task.error_code);
  return (
    <Card className="status-card" title="调研任务">
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        {failure && (
          <Alert
            type="error"
            showIcon
            message={failure.title}
            description={
              <Space direction="vertical" size="small">
                <span>{failure.detail}</span>
                {!failure.retryWorthwhile && (
                  <Typography.Text type="secondary">
                    原样重试会以同样的方式再失败一次。
                  </Typography.Text>
                )}
                <Typography.Text code>{task.error_code}</Typography.Text>
              </Space>
            }
          />
        )}
        <Space wrap>
          <TaskStatusTag status={task.status} />
          <Typography.Text>{getTaskStatusDescription(task.status)}</Typography.Text>
        </Space>
        <Descriptions column={{ xs: 1, sm: 2 }} size="small" items={[
          { key: "task-id", label: "任务 ID", children: <Space size="small"><Typography.Text code className="task-id-short">{formatPublicTaskId(task.task_id)}</Typography.Text>{onCopyTaskId && <Button size="small" aria-label="复制完整任务 ID" onClick={onCopyTaskId}>复制</Button>}</Space> },
          { key: "status", label: "状态", children: <TaskStatusTag status={task.status} /> },
          { key: "created", label: "创建时间", children: formatDate(task.created_at) },
          { key: "updated", label: "更新时间", children: formatDate(task.updated_at) },
          { key: "format", label: "导出格式", children: task.artifact_format?.toUpperCase() ?? "等待生成" }
        ]} />
      </Space>
    </Card>
  );
}
