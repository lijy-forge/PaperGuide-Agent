import { describe, expect, it } from "vitest";
import { getTaskStatusDescription, getTaskStatusLabel, isTerminal, isTerminalStatus, taskStatusPresentation, terminalStatuses } from "../utils/taskStatus";
import { formatDateTime, formatDuration } from "../utils/date";

describe("task status presentation", () => {
  it.each(["created", "queued", "running", "cancel_requested"] as const)("treats %s as active", (status) => expect(isTerminal(status)).toBe(false));
  it.each(["cancelled", "completed", "failed", "human_review", "dead_letter"] as const)("treats %s as terminal", (status) => expect(isTerminal(status)).toBe(true));
  it("defines every actual API status", () => expect(Object.keys(taskStatusPresentation)).toHaveLength(9));
  it("provides text beyond color", () => { for (const item of Object.values(taskStatusPresentation)) { expect(item.label.length).toBeGreaterThan(0); expect(item.description.length).toBeGreaterThan(0); } });
  it("has five terminal statuses", () => expect(terminalStatuses.size).toBe(5));
  it("exposes status label and description helpers", () => { expect(getTaskStatusLabel("human_review")).toBe("等待人工审核"); expect(getTaskStatusDescription("dead_letter")).toBe("任务已达到最大重试次数。"); expect(isTerminalStatus("completed")).toBe(true); });
  it("formats dates in the browser locale and safely handles invalid input", () => { expect(formatDateTime("invalid")).toBe("未知"); expect(formatDateTime("2026-01-01T00:00:00Z")).not.toBe("未知"); });
  it("formats execution duration in milliseconds or seconds", () => { expect(formatDuration(999)).toBe("999 毫秒"); expect(formatDuration(1000)).toBe("1.0 秒"); });
});
