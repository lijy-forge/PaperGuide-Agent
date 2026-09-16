import { Card, Typography } from "antd";
import { useNavigate } from "react-router-dom";
import { ResearchForm } from "../components/ResearchForm";

export function NewResearchPage() {
  const navigate = useNavigate();
  return (
    <div className="page-narrow">
      <Typography.Text className="eyebrow">新建调研</Typography.Text>
      <Typography.Title>PaperGuide 技术调研</Typography.Title>
      <Typography.Paragraph type="secondary">
        创建一个以证据为基础的技术文献调研任务。
      </Typography.Paragraph>
      <Card className="form-card">
        <ResearchForm onSubmitted={(taskId) => navigate(`/tasks/${taskId}`)} />
      </Card>
    </div>
  );
}
