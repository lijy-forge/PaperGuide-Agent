import axios, { AxiosError } from "axios";
import type { ErrorResponse } from "./types";

const configuredBaseUrl = import.meta.env.VITE_PAPERPILOT_API_BASE_URL?.trim();

export const apiClient = axios.create({
  baseURL: configuredBaseUrl || "",
  timeout: 12_000,
  headers: { Accept: "application/json" }
});

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly requestId: string | undefined,
    public readonly status: number | undefined
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function errorResponse(data: unknown): ErrorResponse | undefined {
  if (!data || typeof data !== "object") return undefined;
  const candidate = data as Partial<ErrorResponse>;
  if (
    typeof candidate.code !== "string" ||
    typeof candidate.message !== "string" ||
    typeof candidate.request_id !== "string"
  ) {
    return undefined;
  }
  return candidate as ErrorResponse;
}

function responseRequestId(error: AxiosError<unknown>): string | undefined {
  const value = error.response?.headers?.["x-request-id"];
  if (typeof value === "string" && value.trim()) return value;
  return undefined;
}

async function responseErrorData(data: unknown): Promise<unknown> {
  if (
    typeof Blob !== "undefined" &&
    data instanceof Blob &&
    data.type.toLowerCase().includes("application/json")
  ) {
    try {
      return JSON.parse(await readBlobText(data)) as unknown;
    } catch {
      return undefined;
    }
  }
  return data;
}

function readBlobText(blob: Blob): Promise<string> {
  if (typeof blob.text === "function") return blob.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("blob read failed"));
    reader.readAsText(blob);
  });
}

function validationMessage(data: unknown): string | undefined {
  if (!data || typeof data !== "object" || !("detail" in data)) return undefined;
  const detail = (data as { detail?: Array<{ loc?: Array<string | number>; msg?: string }> }).detail;
  if (!Array.isArray(detail) || detail.length === 0) return undefined;
  return detail.length > 0 ? "请求参数无效。" : undefined;
}

const localizedErrorMessages: Record<string, string> = {
  INVALID_REQUEST: "请求参数无效。",
  TASK_NOT_FOUND: "未找到该任务。",
  TASK_HOST_UNAVAILABLE: "任务主机不可用。",
  RUNTIME_NOT_READY: "运行环境尚未就绪。",
  ARTIFACT_NOT_READY: "调研报告尚未生成。",
  ARTIFACT_NOT_FOUND: "未找到调研报告。",
  ARTIFACT_PATH_INVALID: "调研报告路径无效。",
  INTERNAL_ERROR: "服务暂时不可用，请稍后重试。"
};

function localizedErrorMessage(data: ErrorResponse | undefined): string | undefined {
  if (!data) return undefined;
  return localizedErrorMessages[data.code] ?? "请求处理失败。";
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<unknown>) => {
    const rawData = await responseErrorData(error.response?.data);
    const data = errorResponse(rawData);
    const requestId = responseRequestId(error) ?? data?.request_id;
    const message =
      localizedErrorMessage(data) ??
      validationMessage(rawData) ??
      (error.code === "ECONNABORTED"
        ? "API 请求超时。"
        : "无法连接 PaperPilot API。");
    throw new ApiError(
      data?.code ?? "API_UNAVAILABLE",
      message,
      requestId,
      error.response?.status
    );
  }
);

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "发生意外错误，请重试。";
}
