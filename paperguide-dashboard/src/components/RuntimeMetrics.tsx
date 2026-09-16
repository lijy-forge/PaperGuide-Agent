import { Card, Col, Row, Skeleton, Statistic } from "antd";
import type { MetricsResponse } from "../api/types";
import { formatDuration } from "../utils/date";

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
  { key: "active_workers", label: "活跃工作线程" },
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
  loading = false
}: {
  data?: MetricsResponse;
  loading?: boolean;
}) {
  return (
    <Row gutter={[16, 16]}>
      {metrics.map((metric) => {
        const value = data?.[metric.key] ?? 0;
        return (
          <Col xs={24} sm={12} xl={6} key={metric.key}>
            <Card className="metric-card">
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
