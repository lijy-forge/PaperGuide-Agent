import type { TaskStatusResponse } from "../api/types";
import { TaskOverview } from "./task/TaskOverview";

/** Backwards-compatible overview export used by existing dashboard tests. */
export function TaskStatusCard({ task }: { task: TaskStatusResponse }) {
  return <TaskOverview task={task} />;
}
