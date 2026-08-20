import { apiClient } from "./client";
import type {
  ArtifactResponse,
  TaskEventResponse,
  TaskStatusResponse
} from "./types";
import { safeDownloadFilename } from "../utils/download";

export async function getTask(taskId: string): Promise<TaskStatusResponse> {
  return (await apiClient.get<TaskStatusResponse>(`/api/v1/tasks/${encodeURIComponent(taskId)}`)).data;
}

export async function cancelTask(taskId: string): Promise<TaskStatusResponse> {
  return (await apiClient.post<TaskStatusResponse>(`/api/v1/tasks/${encodeURIComponent(taskId)}/cancel`)).data;
}

export async function getTaskEvents(taskId: string, limit = 20, offset = 0, afterId?: number): Promise<TaskEventResponse[]> {
  return (await apiClient.get<TaskEventResponse[]>(`/api/v1/tasks/${encodeURIComponent(taskId)}/events`, { params: { limit, offset, after_id: afterId } })).data;
}

export async function downloadArtifact(taskId: string): Promise<ArtifactResponse> {
  const response = await apiClient.get<Blob>(`/api/v1/tasks/${encodeURIComponent(taskId)}/artifact`, { responseType: "blob" });
  const contentType = String(response.headers["content-type"] || "application/octet-stream");
  return {
    blob: response.data,
    filename: safeDownloadFilename(response.headers["content-disposition"], taskId, contentType),
    contentType,
    sha256: response.headers["x-artifact-sha256"]
      ? String(response.headers["x-artifact-sha256"])
      : null
  };
}
