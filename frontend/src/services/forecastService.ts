import { apiClient } from "./client";
import type {
  ActionCenterState,
  ExplanationResponse,
  ForecastJobListResponse,
  ForecastJobResponse,
  ForecastRequest,
  ProgressResponse,
  QAResponse,
  SuccessResponse,
} from "@/types/api";

export const forecastService = {
  async submitForecast(
    request: ForecastRequest,
  ): Promise<ForecastJobResponse> {
    const { data } = await apiClient.post<ForecastJobResponse>(
      "/forecast",
      request,
    );
    return data;
  },

  async listJobs(
    limit = 20,
    offset = 0,
  ): Promise<ForecastJobListResponse> {
    const { data } = await apiClient.get<ForecastJobListResponse>(
      "/forecast",
      { params: { limit, offset } },
    );
    return data;
  },

  async renameJob(jobId: string, name: string): Promise<ForecastJobResponse> {
    const { data } = await apiClient.patch<ForecastJobResponse>(
      `/forecast/${jobId}`,
      { name },
    );
    return data;
  },

  async getProgress(jobId: string): Promise<ProgressResponse> {
    const { data } = await apiClient.get<ProgressResponse>(
      `/forecast/${jobId}/progress`,
    );
    return data;
  },

  async getJob(jobId: string): Promise<ForecastJobResponse> {
    const { data } = await apiClient.get<ForecastJobResponse>(
      `/forecast/${jobId}`,
    );
    return data;
  },

  async stopJob(jobId: string): Promise<SuccessResponse> {
    const { data } = await apiClient.delete<SuccessResponse>(
      `/forecast/${jobId}`,
    );
    return data;
  },

  async getActionState(
    jobId: string,
    sheetName: string,
    metricName: string,
  ): Promise<ActionCenterState> {
    const { data } = await apiClient.get<ActionCenterState>(
      `/forecast/${jobId}/actions`,
      { params: { sheet_name: sheetName, metric_name: metricName } },
    );
    return data;
  },

  async applyAction(
    jobId: string,
    sheetName: string,
    metricName: string,
    instructionText: string,
  ): Promise<ActionCenterState> {
    const { data } = await apiClient.post<ActionCenterState>(
      `/forecast/${jobId}/actions`,
      {
        sheet_name: sheetName,
        metric_name: metricName,
        instruction_text: instructionText,
      },
    );
    return data;
  },

  async revertAction(
    jobId: string,
    sheetName: string,
    metricName: string,
  ): Promise<ActionCenterState> {
    const { data } = await apiClient.post<ActionCenterState>(
      `/forecast/${jobId}/actions/revert`,
      { sheet_name: sheetName, metric_name: metricName },
    );
    return data;
  },

  async getExplanation(
    jobId: string,
    sheetName: string,
    metricName: string,
  ): Promise<ExplanationResponse> {
    const { data } = await apiClient.get<ExplanationResponse>(
      `/forecast/${jobId}/explanation`,
      { params: { sheet_name: sheetName, metric_name: metricName } },
    );
    return data;
  },

  async askQuestion(
    jobId: string,
    sheetName: string,
    metricName: string,
    question: string,
  ): Promise<QAResponse> {
    const { data } = await apiClient.post<QAResponse>(
      `/forecast/${jobId}/qa`,
      { sheet_name: sheetName, metric_name: metricName, question },
    );
    return data;
  },

  async exportCsv(
    jobId: string,
    sheetName: string,
    metricName: string,
  ): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(
      `/forecast/${jobId}/export`,
      {
        params: { sheet_name: sheetName, metric_name: metricName },
        responseType: "blob",
      },
    );
    return data;
  },
};