import { Card, Descriptions, Typography } from "antd";
import type { TaskEventResponse, TaskStatusResponse } from "../../api/types";
import { formatDate, formatDuration } from "../../utils/date";
import { formatPublicTaskId } from "../../utils/taskId";
import { getTaskStatusLabel } from "../../utils/taskStatus";

function orderedEvents(events: TaskEventResponse[]): TaskEventResponse[] {
  return [...new Map(events.map((event) => [event.event_id, event])).values()]
    .sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at));
}

export function calculateExecutionDuration(events: TaskEventResponse[]): number | null {
  const ordered = orderedEvents(events);
  if (ordered.length < 2) return null;
  const first = Date.parse(ordered[0].created_at);
  const last = Date.parse(ordered[ordered.length - 1].created_at);
  return Number.isFinite(first) && Number.isFinite(last) ? Math.max(0, last - first) : null;
}

/** Event-derived summary without runtime ownership or persistence details. */
export function TaskSummary({ task, events }: { task: TaskStatusResponse; events: TaskEventResponse[] }) {
  const ordered = orderedEvents(events);
  const duration = task.status === "completed" ? calculateExecutionDuration(events) : null;
  return <Card title="任务摘要">
    <Descriptions column={{ xs: 1, sm: 2 }} size="small" items={[
      { key: "task", label: "任务 ID", children: <Typography.Text code className="task-id-short">{formatPublicTaskId(task.task_id)}</Typography.Text> },
      { key: "status", label: "当前状态", children: getTaskStatusLabel(task.status) },
      { key: "total", label: "事件总数", children: ordered.length },
      { key: "first", label: "首次事件时间", children: ordered.length ? formatDate(ordered[0].created_at) : "暂无" },
      { key: "last", label: "最近事件时间", children: ordered.length ? formatDate(ordered[ordered.length - 1].created_at) : "暂无" },
      { key: "duration", label: "执行时长", children: task.status !== "completed" ? "运行中" : duration == null ? "暂无" : formatDuration(duration) }
    ]} />
  </Card>;
}
