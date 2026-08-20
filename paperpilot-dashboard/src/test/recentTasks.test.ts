import { describe, expect, it } from "vitest";
import { addRecentTask, clearRecentTasks, createLocalTitle, getRecentTasks, removeRecentTask } from "../utils/recentTasks";

const task = (id: number) => ({ taskId: `task-${id}`, createdAt: new Date(2026, 0, id + 1).toISOString(), localTitle: `Question ${id}`, exportFormat: "markdown" as const });

describe("recent task history", () => {
  it("starts empty", () => expect(getRecentTasks()).toEqual([]));
  it("adds a task", () => expect(addRecentTask(task(1))[0].taskId).toBe("task-1"));
  it("places newest first", () => { addRecentTask(task(1)); expect(addRecentTask(task(2)).map((x) => x.taskId)).toEqual(["task-2", "task-1"]); });
  it("deduplicates task ids", () => { addRecentTask(task(1)); addRecentTask({ ...task(1), localTitle: "Updated" }); expect(getRecentTasks()).toHaveLength(1); expect(getRecentTasks()[0].localTitle).toBe("Updated"); });
  it("limits history to twenty items", () => { for (let i = 0; i < 24; i += 1) addRecentTask(task(i)); expect(getRecentTasks()).toHaveLength(20); });
  it("removes one task", () => { addRecentTask(task(1)); addRecentTask(task(2)); expect(removeRecentTask("task-1").map((x) => x.taskId)).toEqual(["task-2"]); });
  it("clears history", () => { addRecentTask(task(1)); clearRecentTasks(); expect(getRecentTasks()).toEqual([]); });
  it("recovers from damaged JSON", () => { localStorage.setItem("paperpilot.recentTasks", "not json"); expect(getRecentTasks()).toEqual([]); });
  it("filters malformed records without rejecting valid history", () => { localStorage.setItem("paperpilot.recentTasks", JSON.stringify([task(1), { taskId: 42, localTitle: "bad" }])); expect(getRecentTasks().map((item) => item.taskId)).toEqual(["task-1"]); });
  it("reads the legacy key and migrates on the next write", () => { localStorage.setItem("paperpilot.recentTasks.v1", JSON.stringify([task(1)])); expect(getRecentTasks()).toHaveLength(1); addRecentTask(task(2)); expect(localStorage.getItem("paperpilot.recentTasks")).toContain("task-2"); expect(localStorage.getItem("paperpilot.recentTasks.v1")).toBeNull(); });
  it("creates a local title capped at sixty characters", () => { const title = createLocalTitle("x".repeat(80)); expect(title).toBe(`${"x".repeat(59)}…`); expect(title).toHaveLength(60); });
});
