import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UserResponse } from "@/types/api";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: UserResponse | null;
  isAuthenticated: boolean;

  setTokens: (access: string, refresh: string) => void;
  setUser: (user: UserResponse) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,

      setTokens: (access, refresh) =>
        set({
          accessToken: access,
          refreshToken: refresh,
          isAuthenticated: true,
        }),

      setUser: (user) => set({ user }),

      logout: () =>
        set({
          accessToken: null,
          refreshToken: null,
          user: null,
          isAuthenticated: false,
        }),
    }),
    {
      name: "forecasting-auth",
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
    },
  ),
);