import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";
import { useAuthStore } from "@/store/authStore";
import type { ApiValidationError } from "@/types/api";

export const apiClient = axios.create({
  baseURL: "/api/v1",
  timeout: 30_000,
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiValidationError | { detail: string }>) => {
    const status = error.response?.status ?? 0;
    const data = error.response?.data;

    let message = "An unexpected error occurred. Please try again.";

    if (data && "detail" in data) {
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (Array.isArray(data.detail)) {
        message = data.detail.map((e) => e.msg).join("; ");
      }
    } else if (error.code === "ECONNABORTED") {
      message = "Request timed out. Please check your connection.";
    } else if (!error.response) {
      message = "Could not reach the server. Please check your connection.";
    }

    if (status === 401) {
      useAuthStore.getState().logout();
    }

    return Promise.reject(new ApiError(message, status, data));
  },
);