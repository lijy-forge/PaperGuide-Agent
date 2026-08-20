import { describe, expect, it } from "vitest";
import { formatPublicTaskId } from "../utils/taskId";

describe("formatPublicTaskId", () => {
  it("redacts a UUID deterministically", () => {
    expect(formatPublicTaskId("2517946f-a38e-42db-8bc8-1f4d00183eb6")).toBe("2517946f…83eb6");
  });

  it("is null-safe and preserves short non-UUID values", () => {
    expect(formatPublicTaskId(undefined)).toBe("任务未标识");
    expect(formatPublicTaskId("task-1")).toBe("task-1");
  });
});
