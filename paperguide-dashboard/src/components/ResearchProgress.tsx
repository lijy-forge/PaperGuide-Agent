import type { TaskEventResponse, TaskStatus } from "../api/types";
import { TaskProgress } from "./task/TaskProgress";

/** Backwards-compatible wrapper. Status is not used to invent unavailable stage events. */
export function ResearchProgress({ events }: { events: TaskEventResponse[]; status: TaskStatus }) {
  return <TaskProgress events={events} />;
}
