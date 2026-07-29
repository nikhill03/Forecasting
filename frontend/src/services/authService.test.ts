import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { authService } from "./authService";
import { ApiError } from "./client";

const validToken = {
  access_token: "access-1",
  refresh_token: "refresh-1",
  token_type: "bearer" as const,
};

const validUser = {
  id: "user-1",
  email: "test@example.com",
  full_name: "Test User",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

describe("authService.register", () => {
  it("returns the parsed token for a well-formed response", async () => {
    server.use(
      http.post("*/api/v1/auth/register", () => HttpResponse.json(validToken)),
    );

    const result = await authService.register({
      email: "test@example.com",
      password: "Secret123",
      full_name: "Test User",
    });
    expect(result).toEqual(validToken);
  });

  it("rejects a request payload with a too-short password before any network call is made", async () => {
    let registerCallCount = 0;
    server.use(
      http.post("*/api/v1/auth/register", () => {
        registerCallCount += 1;
        return HttpResponse.json(validToken);
      }),
    );

    await expect(
      authService.register({
        email: "test@example.com",
        password: "short",
        full_name: "Test User",
      }),
    ).rejects.toThrow(ApiError);
    expect(registerCallCount).toBe(0);
  });

  it("rejects a request payload with a blank full_name before any network call is made", async () => {
    let registerCallCount = 0;
    server.use(
      http.post("*/api/v1/auth/register", () => {
        registerCallCount += 1;
        return HttpResponse.json(validToken);
      }),
    );

    await expect(
      authService.register({
        email: "test@example.com",
        password: "Secret123",
        full_name: "",
      }),
    ).rejects.toThrow(ApiError);
    expect(registerCallCount).toBe(0);
  });
});

describe("authService.refresh", () => {
  it("returns the parsed token for a well-formed response", async () => {
    server.use(
      http.post("*/api/v1/auth/refresh", () => HttpResponse.json(validToken)),
    );

    const result = await authService.refresh("some-refresh-token");
    expect(result).toEqual(validToken);
  });

  it("rejects with ApiError when token_type does not match the expected literal", async () => {
    server.use(
      http.post("*/api/v1/auth/refresh", () =>
        HttpResponse.json({ ...validToken, token_type: "basic" }),
      ),
    );

    await expect(authService.refresh("some-refresh-token")).rejects.toThrow(
      ApiError,
    );
  });
});

describe("authService.login", () => {
  it("returns the parsed token for a well-formed response", async () => {
    server.use(
      http.post("*/api/v1/auth/login", () => HttpResponse.json(validToken)),
    );

    const result = await authService.login({
      email: "test@example.com",
      password: "secret",
    });
    expect(result).toEqual(validToken);
  });

  it("rejects with ApiError when the response is missing a required field", async () => {
    server.use(
      http.post("*/api/v1/auth/login", () =>
        HttpResponse.json({ access_token: "access-1" }),
      ),
    );

    await expect(
      authService.login({ email: "test@example.com", password: "secret" }),
    ).rejects.toThrow(ApiError);
  });

  it("rejects an invalid request payload before hitting the network", async () => {
    let loginCallCount = 0;
    server.use(
      http.post("*/api/v1/auth/login", () => {
        loginCallCount += 1;
        return HttpResponse.json(validToken);
      }),
    );

    await expect(
      authService.login({ email: "not-an-email", password: "secret" }),
    ).rejects.toThrow(ApiError);
    expect(loginCallCount).toBe(0);
  });
});

describe("authService.getMe", () => {
  it("returns the parsed user for a well-formed response", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () => HttpResponse.json(validUser)),
    );

    const result = await authService.getMe();
    expect(result).toEqual(validUser);
  });

  it("rejects with ApiError when the response is wrong-typed", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ ...validUser, is_active: "yes" }),
      ),
    );

    await expect(authService.getMe()).rejects.toThrow(ApiError);
  });

  it("resolves successfully and strips an unrelated extra field instead of throwing", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ ...validUser, role: "admin" }),
      ),
    );

    const result = await authService.getMe();
    expect(result).toEqual(validUser);
    expect(result).not.toHaveProperty("role");
  });
});
