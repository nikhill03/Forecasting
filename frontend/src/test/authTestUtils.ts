import { act } from "@testing-library/react";
import { useAuthStore } from "@/store/authStore";
import type { UserResponse } from "@/types/api";

export function resetAuthStore(): void {
  act(() => {
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
    });
  });
}

export function seedAuthenticatedState(overrides: {
  accessToken?: string;
  refreshToken?: string;
  user?: UserResponse | null;
} = {}): void {
  act(() => {
    useAuthStore.setState({
      accessToken: overrides.accessToken ?? "mock-access-token",
      refreshToken: overrides.refreshToken ?? "mock-refresh-token",
      user: overrides.user ?? null,
      isAuthenticated: true,
    });
  });
}
