import { apiClient } from "./client";
import type { ResearchRequest, TaskAcceptedResponse } from "./types";

export const MAX_RESEARCH_QUESTION_LENGTH = 4_000;

export async function createResearch(
  payload: ResearchRequest
): Promise<TaskAcceptedResponse> {
  const response = await apiClient.post<TaskAcceptedResponse>("/api/v1/research", payload);
  return response.data;
}

/** Existing dashboard compatibility alias. */
export const submitResearch = createResearch;
