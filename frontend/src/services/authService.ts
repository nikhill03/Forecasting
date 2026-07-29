import { apiClient } from "./client";
import { parseOrThrow } from "@/lib/validateResponse";
import {
  TokenResponseSchema,
  UserLoginRequestSchema,
  UserRegisterRequestSchema,
  UserResponseSchema,
} from "@/types/api.schemas";
import type {
  TokenResponse,
  UserLoginRequest,
  UserRegisterRequest,
  UserResponse,
} from "@/types/api";

export const authService = {
  async register(request: UserRegisterRequest): Promise<TokenResponse> {
    const body = parseOrThrow(
      UserRegisterRequestSchema,
      request,
      "authService.register:request",
    );
    const { data } = await apiClient.post<TokenResponse>(
      "/auth/register",
      body,
    );
    return parseOrThrow(TokenResponseSchema, data, "authService.register");
  },

  async login(request: UserLoginRequest): Promise<TokenResponse> {
    const body = parseOrThrow(
      UserLoginRequestSchema,
      request,
      "authService.login:request",
    );
    const { data } = await apiClient.post<TokenResponse>("/auth/login", body);
    return parseOrThrow(TokenResponseSchema, data, "authService.login");
  },

  async refresh(refreshToken: string): Promise<TokenResponse> {
    const { data } = await apiClient.post<TokenResponse>("/auth/refresh", {
      refresh_token: refreshToken,
    });
    return parseOrThrow(TokenResponseSchema, data, "authService.refresh");
  },

  async logout(): Promise<void> {
    await apiClient.post("/auth/logout");
  },

  async getMe(): Promise<UserResponse> {
    const { data } = await apiClient.get<UserResponse>("/auth/me");
    return parseOrThrow(UserResponseSchema, data, "authService.getMe");
  },
};
