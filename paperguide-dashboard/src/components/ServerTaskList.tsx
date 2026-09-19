import { Button, Card, List, Segmented, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import { listTasks } from "../api/tasks";
import type { TaskStatus, TaskStatusResponse } from "../api/types";
import { formatDateTime } from "../utils/date";
import { formatPublicTaskId } from "../utils/taskId";
import { taskStatusPresentation } from "../utils/taskStatus";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";

const PAGE_SIZE = 10;

/** The statuses worth filtering to. A run that ended badly is the one an
 *  operator goes looking for, and it is the one the browser-local list is
 *  least likely to hold, because it was often submitted somewhere else. */
const FILTERS: Array<{ label: string; value: TaskStatus | "all" }> = [
  { label: "全部", value: "all" },
  { label: "失败", value: "failed" },
  { label: "死信", value: "dead_letter" },
  { label: "已取消", value: "cancelled" },
  { label: "已完成", value: "completed" }
];

export function ServerTaskList({
  status = "all",
  onStatusChange
}: {
  status?: TaskStatus | "all";
  onStatusChange?: (status: TaskStatus | "all") => void;
}) {
  const [items, setItems] = useState<TaskStatusResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const mounted = useRef(true);

  // Reset paging whenever the filter changes, or page 3 of one filter would
  // be requested for another that may have only one page.
  useEffect(() => {
    setOffset(0);
  }, [status]);

  const load = useCallback(async () => {
    setLoading(true);
    setFailure(null);
    try {
      const page = await listTasks({
        status: status === "all" ? undefined : status,
        limit: PAGE_SIZE,
        offset
      });
      if (!mounted.current) return;
      setItems(page.items);
      setTotal(page.total);
    } catch (error) {
      if (mounted.current) setFailure(errorMessage(error));
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [status, offset]);

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
    };
  }, [load]);

  return (
    <section aria-labelledby="all-tasks-title">
      <div className="section-heading">
        <div>
          <Typography.Text className="eyebrow">服务端记录</Typography.Text>
          <Typography.Title id="all-tasks-title" level={2}>
            全部任务
          </Typography.Title>
        </div>
        <Space wrap>
          <Segmented
            options={FILTERS}
            value={status}
            onChange={(value) => onStatusChange?.(value as TaskStatus | "all")}
          />
          <Button loading={loading} onClick={() => void load()}>
            刷新
          </Button>
        </Space>
      </div>
      <Card>
        {failure ? (
          <ErrorState message={failure} onRetry={() => void load()} />
        ) : items.length === 0 && !loading ? (
          <EmptyState description="服务端暂无符合条件的任务。" />
        ) : (
          <>
            <List
              loading={loading}
              dataSource={items}
              renderItem={(task) => {
                const presentation = taskStatusPresentation[task.status];
                return (
                  <List.Item
                    actions={[
                      <Link key="open" to={`/tasks/${task.task_id}`}>
                        打开
                      </Link>
                    ]}
                  >
                    <List.Item.Meta
                      title={
                        <Space wrap>
                          <Link to={`/tasks/${task.task_id}`}>
                            调研任务 {formatPublicTaskId(task.task_id)}
                          </Link>
                          <Tag color={presentation.color}>{presentation.label}</Tag>
                        </Space>
                      }
                      description={
                        <Space wrap split={<span aria-hidden="true">·</span>}>
                          <span>{formatDateTime(task.created_at)}</span>
                          {task.error_code && <span>{task.error_code}</span>}
                          {task.artifact_available && <span>有报告</span>}
                        </Space>
                      }
                    />
                  </List.Item>
                );
              }}
            />
            <Space>
              <Button
                disabled={offset === 0 || loading}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                上一页
              </Button>
              <Button
                disabled={offset + PAGE_SIZE >= total || loading}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                下一页
              </Button>
              <Typography.Text type="secondary">
                共 {total} 条，当前 {total === 0 ? 0 : offset + 1}–
                {Math.min(offset + PAGE_SIZE, total)}
              </Typography.Text>
            </Space>
          </>
        )}
      </Card>
    </section>
  );
}
