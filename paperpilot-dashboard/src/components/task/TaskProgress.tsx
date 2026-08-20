import { Badge, Descriptions, Steps, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import type { ProgressEventPayload, ProgressStage, TaskEventResponse } from "../../api/types";
import { formatDuration } from "../../utils/date";

const stageLabels: Record<ProgressStage, string> = {
  query_planning: "规划检索策略", retrieval: "检索候选论文", metadata_filtering: "筛选相关论文",
  pdf_processing: "处理全文 PDF", paper_reading: "阅读论文", evidence_verification: "验证证据",
  final_relevance: "确定核心文献", survey_synthesis: "生成综述", artifact_export: "导出报告"
};
const stages = Object.keys(stageLabels) as ProgressStage[];

export function latestProgress(events: TaskEventResponse[]): ProgressEventPayload | undefined {
  return [...events].sort((a, b) => b.event_id - a.event_id).find((event) => event.progress)?.progress ?? undefined;
}

function stageState(events: TaskEventResponse[], stage: ProgressStage): "finish" | "process" | "wait" | "error" {
  const matching = events.filter((event) => event.progress?.stage === stage);
  if (matching.some((event) => event.event_type === "stage_failed")) return "error";
  if (matching.some((event) => event.event_type === `${stage}_completed`)) return "finish";
  return matching.length ? "process" : "wait";
}

/** User-facing research progress derived only from persisted public events. */
export function TaskProgress({ events, startedAt, terminalAt }: { events: TaskEventResponse[]; startedAt?: string; terminalAt?: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (terminalAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [terminalAt]);
  const latest = useMemo(() => latestProgress(events), [events]);
  if (!events.some((event) => event.progress)) {
    const legacy = [
      ["已创建", "task_created"], ["排队中", "task_queued"], ["运行中", "task_started"], ["已完成", "task_completed"], ["失败", "task_failed"]
    ] as const;
    const recorded = new Set(events.map((event) => event.event_type));
    return <Steps direction="vertical" size="small" current={-1} items={legacy.map(([title, event]) => ({ title, status: recorded.has(event) ? (event === "task_failed" ? "error" : "finish") : "wait", description: recorded.has(event) ? "已记录" : "等待中" }))} />;
  }
  const elapsed = startedAt ? Math.max(0, Date.parse(terminalAt ?? new Date(now).toISOString()) - Date.parse(startedAt)) : null;
  return <div className="research-progress">
    <Descriptions size="small" column={1} items={[
      { key: "stage", label: "当前阶段", children: latest ? stageLabels[latest.stage] : "等待开始" },
      ...(latest?.completed != null && latest.total != null ? [{ key: "count", label: "进度", children: `${latest.completed} / ${latest.total}` }] : []),
      ...(latest?.succeeded != null ? [{ key: "outcome", label: "处理结果", children: `${latest.succeeded} 成功 · ${latest.failed ?? 0} 失败 · ${latest.skipped ?? 0} 跳过` }] : []),
      ...(latest?.paper_title_preview ? [{ key: "paper", label: "当前论文", children: <Typography.Text ellipsis={{ tooltip: latest.paper_title_preview }}>{latest.paper_title_preview}</Typography.Text> }] : []),
      ...(elapsed != null ? [{ key: "elapsed", label: "已运行", children: formatDuration(elapsed) }] : [])
    ]} />
    <Steps direction="vertical" size="small" current={-1} items={stages.map((stage) => {
      const state = stageState(events, stage);
      const payload = [...events].reverse().find((event) => event.progress?.stage === stage)?.progress;
      return { title: stageLabels[stage], status: state, description: payload?.completed != null && payload.total != null ? `${payload.completed} / ${payload.total}${payload.failed ? ` · ${payload.failed} 失败` : ""}` : state === "finish" ? "已完成" : state === "process" ? <Badge status="processing" text="进行中" /> : "等待中" };
    })} />
  </div>;
}
