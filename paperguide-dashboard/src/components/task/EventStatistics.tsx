import { Card, Col, Row, Statistic } from "antd";
import type { TaskEventResponse } from "../../api/types";

const runtimeEvents = new Set(["lease_renewed", "lease_expired"]);
const failureEvents = new Set(["task_failed", "task_dead_letter", "execution_aborted"]);

/** Counts only public event types returned by the Task Event API. */
export function EventStatistics({ events }: { events: TaskEventResponse[] }) {
  const unique = [...new Map(events.map((event) => [event.event_id, event])).values()];
  const statistics = [
    ["事件总数", unique.length],
    ["运行事件", unique.filter((event) => runtimeEvents.has(event.event_type)).length],
    ["失败事件", unique.filter((event) => failureEvents.has(event.event_type)).length],
    ["取消事件", unique.filter((event) => event.event_type === "task_cancelled").length]
  ] as const;
  return <Card title="事件统计"><Row gutter={[12, 12]}>{statistics.map(([title, value]) => <Col xs={12} md={6} key={title}><Statistic title={title} value={value} /></Col>)}</Row></Card>;
}
