import { Alert, Button, Space } from "antd";

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <Alert role="alert" type="error" showIcon message="发生错误" description={<Space direction="vertical"><span>{message}</span>{onRetry && <Button onClick={onRetry}>重试</Button>}</Space>} />;
}
