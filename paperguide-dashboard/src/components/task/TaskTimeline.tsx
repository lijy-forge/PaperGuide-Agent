import { Button, Collapse, Empty, Space, Tabs, Tag, Timeline, Typography } from "antd";
import { useMemo, useState } from "react";
import type { TaskEventResponse, TaskEventType } from "../../api/types";
import { formatDate, formatDuration } from "../../utils/date";
import { TaskStatusTag } from "./TaskStatusTag";

export type TimelineFilter = "all" | "failures" | "runtime";

const eventLabels: Record<string, string> = {
  task_created: "任务已创建", task_queued: "任务已入队", task_started: "任务已启动",
  task_completed: "任务已完成", task_failed: "任务失败", task_cancelled: "任务已取消",
  task_dead_letter: "任务进入死信队列", lease_renewed: "租约已续期", lease_expired: "租约已过期",
  execution_aborted: "执行已中止", stale_worker_rejected: "过期工作线程被拒绝",
  query_planning_started: "开始规划检索", query_planning_completed: "已完成检索规划",
  retrieval_started: "开始检索论文", retrieval_completed: "已完成论文检索",
  metadata_filtering_started: "开始筛选候选论文", metadata_filtering_completed: "已完成候选论文筛选",
  pdf_processing_started: "开始处理全文 PDF", pdf_processing_progress: "正在处理全文 PDF", pdf_processing_completed: "已完成全文 PDF 处理",
  paper_reading_started: "开始阅读论文", paper_reading_progress: "正在阅读论文", paper_reading_completed: "已完成论文阅读",
  evidence_verification_started: "开始验证证据", evidence_verification_progress: "正在验证证据", evidence_verification_completed: "已完成证据验证",
  final_relevance_started: "开始确定核心文献", final_relevance_completed: "已完成核心文献筛选",
  survey_synthesis_started: "开始生成综述", survey_synthesis_completed: "已完成综述生成",
  artifact_export_started: "开始导出报告", artifact_export_completed: "已完成报告导出", stage_failed: "阶段处理失败"
};

const runtimeTypes = new Set<TaskEventType>(["lease_renewed", "lease_expired", "execution_aborted", "stale_worker_rejected"]);
const failureTypes = new Set<TaskEventType>(["task_failed", "task_dead_letter", "execution_aborted", "stale_worker_rejected"]);

function eventGroup(type: TaskEventType): string {
  if (type === "task_cancelled") return "取消";
  if (type === "task_failed" || type === "task_dead_letter") return "失败";
  if (runtimeTypes.has(type)) return "运行时";
  return "生命周期";
}

export function filterTimelineEvents(events: TaskEventResponse[], filter: TimelineFilter): TaskEventResponse[] {
  const unique = [...new Map(events.map((event) => [event.event_id, event])).values()];
  return unique
    .filter((event) => filter === "all" || (filter === "failures" ? failureTypes.has(event.event_type) : runtimeTypes.has(event.event_type)))
    .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at) || right.event_id - left.event_id);
}

/** Filterable, newest-first event history containing public fields only. */
export function TaskTimeline({ events, hasMore, loadingMore, onLoadMore }: { events: TaskEventResponse[]; hasMore: boolean; loadingMore: boolean; onLoadMore: () => void }) {
  const [filter, setFilter] = useState<TimelineFilter>("all");
  const visibleEvents = useMemo(() => filterTimelineEvents(events, filter), [events, filter]);

  async function copyEventTime(createdAt: string) {
    try {
      await navigator.clipboard.writeText(createdAt);
    } catch {
      // Clipboard availability does not affect the timeline.
    }
  }

  return <>
    <Tabs activeKey={filter} onChange={(key) => setFilter(key as TimelineFilter)} items={[
      { key: "all", label: "全部" },
      { key: "failures", label: "失败" },
      { key: "runtime", label: "运行时" }
    ]} />
    {!visibleEvents.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={events.length ? "没有匹配的事件" : "暂无运行事件"} /> : <Timeline className="task-timeline" items={visibleEvents.map((event) => ({
      key: String(event.event_id),
      color: failureTypes.has(event.event_type) ? "red" : event.event_type === "task_completed" ? "green" : "blue",
      children: <div className="timeline-event">
        <Space wrap size="small"><Typography.Text strong ellipsis={{ tooltip: eventLabels[event.event_type] }} className="timeline-event-title">{eventLabels[event.event_type]}</Typography.Text><Tag>{eventGroup(event.event_type)}</Tag></Space>
        <Space wrap size="small"><Typography.Text type="secondary">{formatDate(event.created_at)}</Typography.Text><TaskStatusTag status={event.status} /></Space>
        {event.duration_ms != null && <Typography.Text type="secondary" className="timeline-duration">耗时：{formatDuration(event.duration_ms)}</Typography.Text>}
        <Collapse ghost size="small" items={[{ key: "details", label: "事件详情", children: <Space direction="vertical" size="small"><Typography.Text>状态：{eventLabels[event.event_type]}</Typography.Text><Typography.Text className="event-time-value">事件时间：{event.created_at}</Typography.Text><Button size="small" onClick={() => void copyEventTime(event.created_at)}>复制事件时间</Button></Space> }]} />
      </div>
    }))} />}
    {filter === "all" && hasMore && <Button onClick={onLoadMore} loading={loadingMore}>加载更多</Button>}
  </>;
}
