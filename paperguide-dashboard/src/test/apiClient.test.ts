import {
  AxiosError,
  type AxiosResponse,
  type InternalAxiosRequestConfig
} from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiClient, errorMessage } from "../api/client";
import { createResearch } from "../api/research";
import { getHealth, getMetrics } from "../api/runtime";
import {
  cancelTask,
  downloadArtifact,
  getTask,
  getTaskEvents
} from "../api/tasks";

const originalAdapter = apiClient.defaults.adapter;

function response(
  config: InternalAxiosRequestConfig,
  data: unknown,
  status = 200,
  headers: Record<string, string> = {}
): AxiosResponse {
  return {
    config,
    data,
    status,
    statusText: String(status),
    headers
  };
}

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter;
});

describe("API client", () => {
  it("parses a successful research acknowledgement", async () => {
    apiClient.defaults.adapter = async (config) =>
      response(config, {
        task_id: "task-id",
        status: "queued",
        created_at: "2026-08-06T00:00:00Z"
      });

    const result = await createResearch({
      question: "Evidence-grounded SLAM",
      max_papers: 1,
      export_format: "markdown"
    });

    expect(result).toEqual({
      task_id: "task-id",
      status: "queued",
      created_at: "2026-08-06T00:00:00Z"
    });
  });

  it("parses the stable ErrorResponse envelope", async () => {
    apiClient.defaults.adapter = async (config) => {
      const failed = response(
        config,
        {
          code: "RUNTIME_NOT_READY",
          message: "Runtime unavailable",
          request_id: "body-request-id"
        },
        503
      );
      throw new AxiosError(
        "failed",
        "ERR_BAD_RESPONSE",
        config,
        undefined,
        failed
      );
    };

    await expect(getMetrics()).rejects.toMatchObject({
      code: "RUNTIME_NOT_READY",
      message: "运行环境尚未就绪。",
      requestId: "body-request-id",
      status: 503
    });
  });

  it("prefers X-Request-ID over the error response body", async () => {
    apiClient.defaults.adapter = async (config) => {
      const failed = response(
        config,
        { code: "BAD", message: "Bad", request_id: "body-id" },
        400,
        { "x-request-id": "header-id" }
      );
      throw new AxiosError(
        "failed",
        "ERR_BAD_RESPONSE",
        config,
        undefined,
        failed
      );
    };

    await expect(getHealth()).rejects.toMatchObject({ requestId: "header-id" });
  });

  it("parses an ErrorResponse returned as an artifact JSON blob", async () => {
    apiClient.defaults.adapter = async (config) => {
      const failed = response(
        config,
        new Blob(
          [
            JSON.stringify({
              code: "ARTIFACT_NOT_READY",
              message: "Research artifact is not ready.",
              request_id: "artifact-request-id"
            })
          ],
          { type: "application/json" }
        ),
        409,
        { "x-request-id": "artifact-request-id" }
      );
      throw new AxiosError(
        "failed",
        "ERR_BAD_RESPONSE",
        config,
        undefined,
        failed
      );
    };

    await expect(downloadArtifact("task-id")).rejects.toMatchObject({
      code: "ARTIFACT_NOT_READY",
      requestId: "artifact-request-id",
      status: 409
    });
  });

  it("converts a network failure without exposing the Axios message", async () => {
    apiClient.defaults.adapter = async (config) => {
      throw new AxiosError(
        "sensitive upstream detail",
        "ERR_NETWORK",
        config
      );
    };

    await expect(getTask("task-id")).rejects.toEqual(
      new ApiError(
        "API_UNAVAILABLE",
        "无法连接 PaperGuide API。",
        undefined,
        undefined
      )
    );
  });

  it("does not print request bodies, questions, or tokens", async () => {
    const spies = [
      vi.spyOn(console, "log"),
      vi.spyOn(console, "info"),
      vi.spyOn(console, "warn"),
      vi.spyOn(console, "error")
    ];
    apiClient.defaults.adapter = async (config) =>
      response(config, {
        task_id: "safe-id",
        status: "queued",
        created_at: "2026-08-06T00:00:00Z"
      });

    await createResearch({
      question: "private research question",
      max_papers: 1,
      export_format: "markdown"
    });

    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });

  it("uses the exact task, cancellation, and event routes", async () => {
    const urls: string[] = [];
    apiClient.defaults.adapter = async (config) => {
      urls.push(config.url ?? "");
      return response(config, []);
    };

    await getTask("task/id");
    await cancelTask("task/id");
    await getTaskEvents("task/id", 10, 5);

    expect(urls).toEqual([
      "/api/v1/tasks/task%2Fid",
      "/api/v1/tasks/task%2Fid/cancel",
      "/api/v1/tasks/task%2Fid/events"
    ]);
  });

  it("maps artifact body and public response headers", async () => {
    apiClient.defaults.adapter = async (config) =>
      response(config, new Blob(["report"]), 200, {
        "content-disposition": 'attachment; filename="research-report.md"',
        "content-type": "text/markdown; charset=utf-8",
        "x-artifact-sha256": "abc123"
      });

    const result = await downloadArtifact("task-id");

    expect(result.filename).toBe("research-report.md");
    expect(result.contentType).toBe("text/markdown; charset=utf-8");
    expect(result.sha256).toBe("abc123");
    expect(result.blob).toBeInstanceOf(Blob);
  });

  it("accepts HTTP 503 readiness as a structured health response", async () => {
    apiClient.defaults.adapter = async (config) =>
      response(
        config,
        { kind: "readiness", status: "unhealthy", ready: false, checks: [] },
        503
      );

    expect(await getHealth()).toMatchObject({ ready: false, status: "unhealthy" });
  });

  it("supports the liveness endpoint without adding another transport", async () => {
    let requestedUrl = "";
    apiClient.defaults.adapter = async (config) => {
      requestedUrl = config.url ?? "";
      return response(config, {
        kind: "liveness",
        status: "healthy",
        ready: true,
        checks: []
      });
    };

    expect((await getHealth("live")).kind).toBe("liveness");
    expect(requestedUrl).toBe("/health/live");
  });

  it("provides only safe UI fallback messages", () => {
    expect(errorMessage({ secret: "x" })).toBe(
      "发生意外错误，请重试。"
    );
    expect(errorMessage(new ApiError("BAD", "Safe", undefined, 400))).toBe(
      "Safe"
    );
  });
});
