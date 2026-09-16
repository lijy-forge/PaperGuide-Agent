import { Flex, Spin, Typography } from "antd";

export function LoadingState({ label = "正在加载" }: { label?: string }) {
  return (
    <Flex vertical align="center" gap="small" className="loading-state">
      <Spin aria-label={label} />
      <Typography.Text type="secondary">{label}</Typography.Text>
    </Flex>
  );
}
