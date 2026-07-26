import { http, HttpResponse } from "msw";
import type { TokenResponse, UserResponse } from "@/types/api";

export const validTokenResponse: TokenResponse = {
  access_token: "mock-access-token",
  refresh_token: "mock-refresh-token",
  token_type: "bearer",
};

export const mockUser: UserResponse = {
  id: "user-1",
  email: "test@example.com",
  full_name: "Test User",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

export const handlers = [
  http.post("*/api/v1/auth/login", () => HttpResponse.json(validTokenResponse)),
  http.post("*/api/v1/auth/refresh", () => HttpResponse.json(validTokenResponse)),
  http.get("*/api/v1/auth/me", () => HttpResponse.json(mockUser)),
];
