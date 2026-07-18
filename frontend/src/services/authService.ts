import { apiClient } from "./client";
import type {
  TokenResponse,
  UserLoginRequest,
  UserRegisterRequest,
  UserResponse,
} from "@/types/api";

export const authService = {
  async register(request: UserRegisterRequest): Promise<TokenResponse> {
    const { data } = await apiClient.post<TokenResponse>(
      "/auth/register",
      request,
    );
    return data;
  },

  async login(request: UserLoginRequest): Promise<TokenResponse> {
    const { data } = await apiClient.post<TokenResponse>(
      "/auth/login",
      request,
    );
    return data;
  },

  async refresh(refreshToken: string): Promise<TokenResponse> {
    const { data } = await apiClient.post<TokenResponse>("/auth/refresh", {
      refresh_token: refreshToken,
    });
    return data;
  },

  async logout(): Promise<void> {
    await apiClient.post("/auth/logout");
  },

  async getMe(): Promise<UserResponse> {
    const { data } = await apiClient.get<UserResponse>("/auth/me");
    return data;
  },
};