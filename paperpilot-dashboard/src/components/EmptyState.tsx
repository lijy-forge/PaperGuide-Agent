import { Empty, Button } from "antd";
import { Link } from "react-router-dom";

export function EmptyState({ description = "当前浏览器中暂无调研任务。" }: { description?: string }) {
  return <Empty description={description}><Link to="/research/new"><Button type="primary">新建调研</Button></Link></Empty>;
}
