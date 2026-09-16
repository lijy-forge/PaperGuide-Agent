import { Tag } from "antd";
import type { TaskStatus } from "../../api/types";
import { getTaskStatusLabel, taskStatusPresentation } from "../../utils/taskStatus";

/** Accessible task status presentation with text as well as color. */
export function TaskStatusTag({ status }: { status: TaskStatus }) {
  return <Tag color={taskStatusPresentation[status].color}>{getTaskStatusLabel(status)}</Tag>;
}
