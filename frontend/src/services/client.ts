import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";
import { useAuthStore } from "@/store/authStore";
import type { ApiValidationError } from "@/types/api";
import { ApiValidationErrorSchema } from "@/types/api.schemas";
// Circular import with authService.ts (which imports apiClient from here) is
// intentional and safe: both modules only touch the cyclic binding inside
// function bodies, never at module-evaluation time.
import { authService } from "@/services/authService";

declare module "axios" {
  export interface InternalAxiosRequestConfig {
    _retry?: boolean;
  }
}

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

function buildApiError(error: AxiosError<ApiValidationError | { detail: string }>): ApiError {
  const status = error.response?.status ?? 0;
  const data = error.response?.data;

  let message = "An unexpected error occurred. Please try again.";

  if (data && "detail" in data) {
    if (typeof data.detail === "string") {
      message = data.detail;
    } else {
      const parsed = ApiValidationErrorSchema.safeParse(data);
      if (parsed.success) {
        message = parsed.data.detail.map((e) => e.msg).join("; ");
      }
    }
  } else if (error.code === "ECONNABORTED") {
    message = "Request timed out. Please check your connection.";
  } else if (!error.response) {
    message = "Could not reach the server. Please check your connection.";
  }

  return new ApiError(message, status, data);
}

function isUrlMatch(url: string | undefined, path: string): boolean {
  return url !== undefined && (url === path || url.endsWith(path));
}

let refreshPromise: Promise<string> | null = null;

function refreshAccessToken(): Promise<string> {
  if (refreshPromise) {
    return refreshPromise;
  }

  const currentRefreshToken = useAuthStore.getState().refreshToken;
  if (!currentRefreshToken) {
    return Promise.reject(new Error("No refresh token available"));
  }

  refreshPromise = authService
    .refresh(currentRefreshToken)
    .then((tokens) => {
      useAuthStore.getState().setTokens(tokens.access_token, tokens.refresh_token);
      return tokens.access_token;
    })
    .finally(() => {
      refreshPromise = null;
    });

  return refreshPromise;
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiValidationError | { detail: string }>) => {
    const status = error.response?.status ?? 0;
    const originalRequest = error.config;

    const isRefreshCall = isUrlMatch(originalRequest?.url, "/auth/refresh");
    const isLoginCall = isUrlMatch(originalRequest?.url, "/auth/login");

    if (status === 401 && isRefreshCall) {
      // The refresh token itself is invalid/expired. This rejection also
      // propagates through refreshAccessToken() back to the retry branch's
      // catch below, which calls logout() a second time — harmless, since
      // logout() just resets already-cleared state, but noted so a future
      // reader doesn't "fix" the apparent duplication.
      useAuthStore.getState().logout();
      return Promise.reject(buildApiError(error));
    }

    if (status === 401 && originalRequest?._retry) {
      // Already retried once with a freshly refreshed token and still 401
      // (e.g. account disabled server-side) — stop here instead of leaving
      // stale tokens/isAuthenticated=true in the store indefinitely.
      useAuthStore.getState().logout();
      return Promise.reject(buildApiError(error));
    }

    if (status === 401 && !isLoginCall && originalRequest) {
      originalRequest._retry = true;
      try {
        // No need to set Authorization here — the request interceptor
        // (above) re-reads the store's accessToken, now refreshed, on
        // every dispatch, including this retry.
        await refreshAccessToken();
        return apiClient(originalRequest);
      } catch {
        useAuthStore.getState().logout();
        return Promise.reject(buildApiError(error));
      }
    }

    return Promise.reject(buildApiError(error));
  },
);
