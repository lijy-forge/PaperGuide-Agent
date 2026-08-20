import { Button, Card, List, Popconfirm, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { getTask } from "../api/tasks";
import type { TaskStatusResponse } from "../api/types";
import { formatDateTime } from "../utils/date";
import { formatPublicTaskId } from "../utils/taskId";
import {
  clearRecentTasks,
  getRecentTasks,
  removeRecentTask,
  type RecentTaskRecord
} from "../utils/recentTasks";
import { taskStatusPresentation } from "../utils/taskStatus";
import { EmptyState } from "./EmptyState";

type RemoteTaskState =
  | { kind: "loaded"; task: TaskStatusResponse }
  | { kind: "not_found" }
  | { kind: "unavailable" };

async function loadTaskBatch(
  records: RecentTaskRecord[]
): Promise<Record<string, RemoteTaskState>> {
  const result: Record<string, RemoteTaskState> = {};
  for (let index = 0; index < records.length; index += 5) {
    const batch = records.slice(index, index + 5);
    const entries = await Promise.all(
      batch.map(async (record): Promise<[string, RemoteTaskState]> => {
        try {
          return [record.taskId, { kind: "loaded", task: await getTask(record.taskId) }];
        } catch (error) {
          return [
            record.taskId,
            error instanceof ApiError && error.status === 404
              ? { kind: "not_found" }
              : { kind: "unavailable" }
          ];
        }
      })
    );
    Object.assign(result, Object.fromEntries(entries));
  }
  return result;
}

function publicTaskTitle(title: string, taskId: string): string {
  const safeTitle = title.trim();
  const isCanonicalUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(taskId);
  if (!safeTitle || (isCanonicalUuid && (safeTitle === taskId || safeTitle === `Research ${taskId}`))) {
    return `调研任务 ${formatPublicTaskId(taskId)}`;
  }
  return safeTitle;
}

export function RecentTasks() {
  const [records, setRecords] = useState<RecentTaskRecord[]>(() => getRecentTasks());
  const [remote, setRemote] = useState<Record<string, RemoteTaskState>>({});
  const [refreshing, setRefreshing] = useState(false);
  const mounted = useRef(true);
  const inFlight = useRef<Promise<void> | null>(null);

  const refresh = useCallback(() => {
    if (inFlight.current) return inFlight.current;
    setRefreshing(true);
    const request = loadTaskBatch(records).then((next) => {
      if (mounted.current) setRemote(next);
    }).finally(() => {
      if (mounted.current) setRefreshing(false);
    });
    inFlight.current = request.finally(() => {
      inFlight.current = null;
    });
    return inFlight.current;
  }, [records]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
    };
  }, [refresh]);

  const remove = (taskId: string) => {
    setRecords(removeRecentTask(taskId));
    setRemote((current) => {
      const next = { ...current };
      delete next[taskId];
      return next;
    });
  };

  return (
    <section aria-labelledby="recent-research-title">
      <div className="section-heading">
        <div>
          <Typography.Text className="eyebrow">当前浏览器</Typography.Text>
          <Typography.Title id="recent-research-title" level={2}>
            最近调研
          </Typography.Title>
        </div>
        <Space>
          <Button loading={refreshing} onClick={() => void refresh()}>
            刷新
          </Button>
          {records.length > 0 && (
            <Popconfirm
              title="清除本地任务历史记录？"
              okText="确认"
              cancelText="返回"
              onConfirm={() => {
                clearRecentTasks();
                setRecords([]);
                setRemote({});
              }}
            >
              <Button>清除历史</Button>
            </Popconfirm>
          )}
        </Space>
      </div>
      <Card>
        {records.length === 0 ? (
          <EmptyState />
        ) : (
          <List
            dataSource={records}
            renderItem={(record) => {
              const state = remote[record.taskId];
              const presentation =
                state?.kind === "loaded"
                  ? taskStatusPresentation[state.task.status]
                  : undefined;
              const stateLabel =
                state?.kind === "not_found"
                  ? "未找到"
                  : state?.kind === "unavailable"
                    ? "不可用"
                    : presentation?.label ?? "正在检查";
              return (
                <List.Item
                  actions={[
                    <Link key="open" to={`/tasks/${record.taskId}`}>打开</Link>,
                    <Popconfirm
                      key="remove"
                      title="从本地历史记录中移除此任务？"
                      okText="确认"
                      cancelText="返回"
                      onConfirm={() => remove(record.taskId)}
                    >
                      <Button type="link" danger>移除</Button>
                    </Popconfirm>
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space wrap>
                        <Link to={`/tasks/${record.taskId}`}>{publicTaskTitle(record.localTitle, record.taskId)}</Link>
                        <Tag color={presentation?.color}>{stateLabel}</Tag>
                      </Space>
                    }
                    description={
                      <Space wrap split={<span aria-hidden="true">·</span>}>
                        <span>{formatDateTime(record.createdAt)}</span>
                        <span>{record.exportFormat.toUpperCase()}</span>
                        <Typography.Text code className="task-id">
                          {formatPublicTaskId(record.taskId)}
                        </Typography.Text>
                        <Button
                          size="small"
                          aria-label="复制完整任务 ID"
                          onClick={() => void navigator.clipboard.writeText(record.taskId)}
                        >
                          复制 ID
                        </Button>
                      </Space>
                    }
                  />
                </List.Item>
              );
            }}
          />
        )}
      </Card>
    </section>
  );
}
