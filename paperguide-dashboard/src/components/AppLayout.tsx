import { Button, Layout, Menu, Typography } from "antd";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useRuntimeHealth } from "../hooks/useRuntimeHealth";
import { HealthIndicator } from "./HealthIndicator";

const { Header, Sider, Content } = Layout;

export interface AppOutletContext {
  runtimeHealth: ReturnType<typeof useRuntimeHealth>;
}

export function AppLayout() {
  const location = useLocation();
  const runtimeHealth = useRuntimeHealth();
  const selected = location.pathname.startsWith("/research/new") ? "/research/new" : location.pathname.startsWith("/tasks/") ? "/tasks" : "/";
  return <Layout className="app-shell">
    <Sider breakpoint="lg" collapsedWidth="0" className="app-sider">
      <Link className="brand brand-side" to="/">PaperGuide <span>AI</span></Link>
      <Menu theme="dark" mode="inline" selectedKeys={[selected]} items={[
        { key: "/", label: <Link to="/">工作台</Link> },
        { key: "/research/new", label: <Link to="/research/new">新建调研</Link> },
        { key: "/tasks", label: "任务详情", disabled: !location.pathname.startsWith("/tasks/") }
      ]} />
    </Sider>
    <Layout>
      <Header className="app-header">
        <div><Typography.Text className="eyebrow">技术调研中心</Typography.Text><Typography.Title level={4}>PaperGuide AI</Typography.Title></div>
        <div className="header-actions"><HealthIndicator state={runtimeHealth.state} /><Link to="/research/new"><Button type="primary">新建调研</Button></Link></div>
      </Header>
      <Content className="app-content"><Outlet context={{ runtimeHealth }} /></Content>
    </Layout>
  </Layout>;
}
