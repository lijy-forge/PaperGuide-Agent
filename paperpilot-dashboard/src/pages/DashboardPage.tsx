import { Alert, Button, Card, Typography } from "antd";
import { Link, useOutletContext } from "react-router-dom";
import { errorMessage } from "../api/client";
import type { AppOutletContext } from "../components/AppLayout";
import { RecentTasks } from "../components/RecentTasks";
import { RuntimeMetrics } from "../components/RuntimeMetrics";
import { useRuntimeMetrics } from "../hooks/useRuntimeMetrics";

export function DashboardPage() {
  const { runtimeHealth } = useOutletContext<AppOutletContext>();
  const metrics = useRuntimeMetrics();

  return (
    <div className="page-stack">
      <section className="hero-panel">
        <div>
          <Typography.Text className="eyebrow">PAPERPILOT AI</Typography.Text>
          <Typography.Title>PaperPilot AI</Typography.Title>
          <Typography.Paragraph>
            证据驱动的技术深度调研智能体
          </Typography.Paragraph>
        </div>
        <Link to="/research/new">
          <Button size="large" type="primary">新建调研</Button>
        </Link>
      </section>

      {runtimeHealth.state === "host_offline" && (
        <Alert
          role="alert"
          type="error"
          showIcon
          message="任务主机不可用"
          description={<>请运行以下命令启动：<Typography.Text code>paperpilot server start</Typography.Text></>}
        />
      )}
      {runtimeHealth.state === "degraded" && (
        <Alert
          role="alert"
          type="warning"
          showIcon
          message="运行环境降级"
          description="API 已在线，但一个或多个运行状态检查不可用。"
        />
      )}
      {runtimeHealth.state === "api_offline" && (
        <Alert
          role="alert"
          type="error"
          showIcon
          message="API 离线"
          description="无法连接 PaperPilot API。"
        />
      )}

      <section aria-labelledby="runtime-metrics-title">
        <div className="section-heading">
          <div>
            <Typography.Text className="eyebrow">运行状态</Typography.Text>
            <Typography.Title id="runtime-metrics-title" level={2}>
              系统指标
            </Typography.Title>
          </div>
          <Button loading={metrics.loading} onClick={() => void metrics.refresh()}>
            刷新指标
          </Button>
        </div>
        {Boolean(metrics.error) && (
          <Alert
            role="alert"
            type="error"
            showIcon
            message="指标不可用"
            description={errorMessage(metrics.error)}
            className="section-alert"
          />
        )}
        <RuntimeMetrics data={metrics.data} loading={metrics.loading && !metrics.data} />
      </section>

      <RecentTasks />

      <Card className="quick-start-card">
        <Typography.Title level={3}>创建新的文献调研任务</Typography.Title>
        <Typography.Paragraph>
          搜索论文、解析 PDF、核验证据，并生成可审计的技术报告。
        </Typography.Paragraph>
        <Link to="/research/new"><Button type="primary">新建调研</Button></Link>
      </Card>
    </div>
  );
}
