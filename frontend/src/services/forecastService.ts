import { apiClient } from "./client";
import type {
  ForecastJobResponse,
  ForecastRequest,
  ProgressResponse,
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
};