import { Card, Col, Row, Skeleton, Statistic } from "antd";
import type { MetricsResponse, TaskStatus } from "../api/types";
import { formatDuration } from "../utils/date";

/** Counters that name a task status you can go and look at. A count with no
 *  way to open the tasks behind it tells an operator something went wrong and
 *  nothing about what. */
const DRILLDOWN: Partial<Record<keyof MetricsResponse, TaskStatus>> = {
  failed_total: "failed",
  cancelled_total: "cancelled",
  dead_letter_total: "dead_letter",
  completed_total: "completed"
};

const metrics: Array<{
  key: keyof MetricsResponse;
  label: string;
  formatter?: (value: number) => string;
}> = [
  { key: "submitted_total", label: "已提交" },
  { key: "completed_total", label: "已完成" },
  { key: "failed_total", label: "失败" },
  { key: "cancelled_total", label: "已取消" },
  { key: "dead_letter_total", label: "死信任务" },
  // Counts distinct lease holders, and a lease is held by a host rather than
  // by a worker thread, so on a single-host deployment this is 0 or 1 however
  // many tasks run at once. Labelling it 工作线程 made it look broken whenever
  // 运行中任务 was higher.
  { key: "active_workers", label: "活跃 Host 数" },
  { key: "queue_size", label: "队列长度" },
  { key: "running_tasks", label: "运行中任务" },
  {
    key: "average_execution_time_ms",
    label: "平均执行时间",
    formatter: formatDuration
  }
];

export function RuntimeMetrics({
  data,
  loading = false,
  onSelectStatus
}: {
  data?: MetricsResponse;
  loading?: boolean;
  onSelectStatus?: (status: TaskStatus) => void;
}) {
  return (
    <Row gutter={[16, 16]}>
      {metrics.map((metric) => {
        const value = data?.[metric.key] ?? 0;
        const status = DRILLDOWN[metric.key];
        const clickable = Boolean(status && onSelectStatus);
        return (
          <Col xs={24} sm={12} xl={6} key={metric.key}>
            <Card
              className="metric-card"
              hoverable={clickable}
              onClick={clickable ? () => onSelectStatus?.(status!) : undefined}
              role={clickable ? "button" : undefined}
              tabIndex={clickable ? 0 : undefined}
              aria-label={clickable ? `查看${metric.label}的任务` : undefined}
              onKeyDown={
                clickable
                  ? (event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelectStatus?.(status!);
                      }
                    }
                  : undefined
              }
            >
              {loading ? (
                <Skeleton active paragraph={false} />
              ) : (
                <Statistic
                  title={metric.label}
                  value={metric.formatter ? metric.formatter(value) : value}
                />
              )}
            </Card>
          </Col>
        );
      })}
    </Row>
  );
}
