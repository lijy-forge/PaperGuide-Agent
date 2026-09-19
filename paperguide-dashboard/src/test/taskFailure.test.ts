import { describe, expect, it } from "vitest";
import { explainFailure } from "../utils/taskFailure";

describe("explainFailure", () => {
  it("says nothing when the task did not fail", () => {
    expect(explainFailure(null)).toBeNull();
  });

  it("tells the reader that retrying a year-range failure is pointless", () => {
    const failure = explainFailure("NO_PAPERS_IN_TIME_RANGE");
    expect(failure?.retryWorthwhile).toBe(false);
    expect(failure?.detail).toContain("年份");
  });

  it("keeps retry open where the cause may be transient", () => {
    expect(explainFailure("NO_EVIDENCE_FOR_QUESTION")?.retryWorthwhile).toBe(true);
    expect(explainFailure("REPORT_QUALITY_REJECTED")?.retryWorthwhile).toBe(true);
  });

  it("does not offer retry for a dead-lettered task", () => {
    expect(explainFailure("TASK_DEAD_LETTER")?.retryWorthwhile).toBe(false);
  });

  it("falls back rather than leaving an unknown code unexplained", () => {
    // A new server code must not produce a blank panel: the reader would see a
    // failed task with no stated reason at all.
    const failure = explainFailure("SOME_FUTURE_CODE");
    expect(failure).not.toBeNull();
    expect(failure?.title.length).toBeGreaterThan(0);
  });
});
