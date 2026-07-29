import { apiClient } from "./client";
import { parseOrThrow } from "@/lib/validateResponse";
import {
  ActionCenterStateSchema,
  ApplyActionRequestSchema,
  ExplanationResponseSchema,
  ForecastJobListResponseSchema,
  ForecastJobResponseSchema,
  ForecastRequestSchema,
  ProgressResponseSchema,
  QARequestSchema,
  QAResponseSchema,
  RenameJobRequestSchema,
  RevertActionRequestSchema,
  SuccessResponseSchema,
} from "@/types/api.schemas";
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
    const body = parseOrThrow(
      ForecastRequestSchema,
      request,
      "forecastService.submitForecast:request",
    );
    const { data } = await apiClient.post<ForecastJobResponse>(
      "/forecast",
      body,
    );
    return parseOrThrow(
      ForecastJobResponseSchema,
      data,
      "forecastService.submitForecast",
    );
  },

  async listJobs(
    limit = 20,
    offset = 0,
  ): Promise<ForecastJobListResponse> {
    const { data } = await apiClient.get<ForecastJobListResponse>(
      "/forecast",
      { params: { limit, offset } },
    );
    return parseOrThrow(
      ForecastJobListResponseSchema,
      data,
      "forecastService.listJobs",
    );
  },

  async renameJob(jobId: string, name: string): Promise<ForecastJobResponse> {
    const body = parseOrThrow(
      RenameJobRequestSchema,
      { name },
      "forecastService.renameJob:request",
    );
    const { data } = await apiClient.patch<ForecastJobResponse>(
      `/forecast/${jobId}`,
      body,
    );
    return parseOrThrow(
      ForecastJobResponseSchema,
      data,
      "forecastService.renameJob",
    );
  },

  async getProgress(jobId: string): Promise<ProgressResponse> {
    const { data } = await apiClient.get<ProgressResponse>(
      `/forecast/${jobId}/progress`,
    );
    return parseOrThrow(
      ProgressResponseSchema,
      data,
      "forecastService.getProgress",
    );
  },

  async getJob(jobId: string): Promise<ForecastJobResponse> {
    const { data } = await apiClient.get<ForecastJobResponse>(
      `/forecast/${jobId}`,
    );
    return parseOrThrow(
      ForecastJobResponseSchema,
      data,
      "forecastService.getJob",
    );
  },

  async stopJob(jobId: string): Promise<SuccessResponse> {
    const { data } = await apiClient.delete<SuccessResponse>(
      `/forecast/${jobId}`,
    );
    return parseOrThrow(
      SuccessResponseSchema,
      data,
      "forecastService.stopJob",
    );
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
    return parseOrThrow(
      ActionCenterStateSchema,
      data,
      "forecastService.getActionState",
    );
  },

  async applyAction(
    jobId: string,
    sheetName: string,
    metricName: string,
    instructionText: string,
  ): Promise<ActionCenterState> {
    const body = parseOrThrow(
      ApplyActionRequestSchema,
      {
        sheet_name: sheetName,
        metric_name: metricName,
        instruction_text: instructionText,
      },
      "forecastService.applyAction:request",
    );
    const { data } = await apiClient.post<ActionCenterState>(
      `/forecast/${jobId}/actions`,
      body,
    );
    return parseOrThrow(
      ActionCenterStateSchema,
      data,
      "forecastService.applyAction",
    );
  },

  async revertAction(
    jobId: string,
    sheetName: string,
    metricName: string,
  ): Promise<ActionCenterState> {
    const body = parseOrThrow(
      RevertActionRequestSchema,
      { sheet_name: sheetName, metric_name: metricName },
      "forecastService.revertAction:request",
    );
    const { data } = await apiClient.post<ActionCenterState>(
      `/forecast/${jobId}/actions/revert`,
      body,
    );
    return parseOrThrow(
      ActionCenterStateSchema,
      data,
      "forecastService.revertAction",
    );
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
    return parseOrThrow(
      ExplanationResponseSchema,
      data,
      "forecastService.getExplanation",
    );
  },

  async askQuestion(
    jobId: string,
    sheetName: string,
    metricName: string,
    question: string,
  ): Promise<QAResponse> {
    const body = parseOrThrow(
      QARequestSchema,
      { sheet_name: sheetName, metric_name: metricName, question },
      "forecastService.askQuestion:request",
    );
    const { data } = await apiClient.post<QAResponse>(
      `/forecast/${jobId}/qa`,
      body,
    );
    return parseOrThrow(
      QAResponseSchema,
      data,
      "forecastService.askQuestion",
    );
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
