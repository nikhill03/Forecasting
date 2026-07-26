import { describe, it, expect, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { apiClient } from "./client";
import { useAuthStore } from "@/store/authStore";

function seedAuthenticatedState(): void {
  useAuthStore.setState({
    accessToken: "expired-access-token",
    refreshToken: "valid-refresh-token",
    user: null,
    isAuthenticated: true,
  });
}

describe("apiClient 401 refresh interceptor", () => {
  beforeEach(() => {
    seedAuthenticatedState();
  });

  it("dedupes 3 concurrent 401s into exactly one /auth/refresh call, then retries all three", async () => {
    let meCallCount = 0;
    let refreshCallCount = 0;

    server.use(
      http.get("*/api/v1/auth/me", () => {
        meCallCount += 1;
        if (meCallCount <= 3) {
          return HttpResponse.json({ detail: "Token expired" }, { status: 401 });
        }
        return HttpResponse.json({
          id: "user-1",
          email: "a@b.com",
          full_name: "A B",
          is_active: true,
          created_at: "2026-01-01T00:00:00Z",
        });
      }),
      http.post("*/api/v1/auth/refresh", () => {
        refreshCallCount += 1;
        return HttpResponse.json({
          access_token: "new-access",
          refresh_token: "new-refresh",
          token_type: "bearer",
        });
      }),
    );

    const results = await Promise.all([
      apiClient.get("/auth/me"),
      apiClient.get("/auth/me"),
      apiClient.get("/auth/me"),
    ]);

    expect(refreshCallCount).toBe(1);
    results.forEach((r) => expect(r.status).toBe(200));
    expect(useAuthStore.getState().accessToken).toBe("new-access");
  });

  it("logs out with no infinite loop when /auth/refresh itself returns 401", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ detail: "Token expired" }, { status: 401 }),
      ),
      http.post("*/api/v1/auth/refresh", () =>
        HttpResponse.json({ detail: "Invalid refresh token" }, { status: 401 }),
      ),
    );

    await expect(apiClient.get("/auth/me")).rejects.toThrow();

    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("logs out with no infinite loop when the retried request still 401s after a successful refresh", async () => {
    let refreshCallCount = 0;

    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ detail: "Token expired" }, { status: 401 }),
      ),
      http.post("*/api/v1/auth/refresh", () => {
        refreshCallCount += 1;
        return HttpResponse.json({
          access_token: "new-access",
          refresh_token: "new-refresh",
          token_type: "bearer",
        });
      }),
    );

    await expect(apiClient.get("/auth/me")).rejects.toThrow();

    expect(refreshCallCount).toBe(1);
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("does not attempt refresh and does not log out on a failed /auth/login", async () => {
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
    });

    let refreshCallCount = 0;
    server.use(
      http.post("*/api/v1/auth/login", () =>
        HttpResponse.json({ detail: "Invalid credentials" }, { status: 401 }),
      ),
      http.post("*/api/v1/auth/refresh", () => {
        refreshCallCount += 1;
        return HttpResponse.json({ detail: "should not be called" }, { status: 401 });
      }),
    );

    await expect(
      apiClient.post("/auth/login", { email: "a@b.com", password: "wrong" }),
    ).rejects.toThrow();

    expect(refreshCallCount).toBe(0);
  });
});
