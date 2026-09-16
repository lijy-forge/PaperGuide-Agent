import { Badge, Popover, Typography } from "antd";
import type { HealthState } from "../hooks/useRuntimeHealth";

const presentation: Record<
  HealthState,
  {
    status: "success" | "error" | "warning" | "processing";
    label: string;
  }
> = {
  checking: { status: "processing", label: "正在检查" },
  ready: { status: "success", label: "运行环境就绪" },
  host_offline: { status: "error", label: "任务主机离线" },
  degraded: { status: "warning", label: "运行环境降级" },
  api_offline: { status: "error", label: "API 离线" }
};

export function HealthIndicator({ state }: { state: HealthState }) {
  const item = presentation[state];
  const content =
    state === "host_offline" ? (
      <Typography.Text>
        任务主机不可用，请运行：{" "}
        <Typography.Text code>paperguide server start</Typography.Text>
      </Typography.Text>
    ) : (
      <span>PaperGuide API 与运行环境状态。</span>
    );
  return (
    <Popover content={content} title={item.label}>
      <span className="health-indicator" aria-label={item.label}>
        <Badge status={item.status} text={item.label} />
      </span>
    </Popover>
  );
}
