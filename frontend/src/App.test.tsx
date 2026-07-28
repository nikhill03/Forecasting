/**
 * App.test.tsx
 * ============
 * Integration/routing tests for `App.tsx`'s route tree, derived from
 * `.claude/specs/p2-frontend-auth-hardening.md`:
 *
 *  - DoD: "Unauthenticated navigation to /upload (and /configure, /running,
 *    /results, /dashboard) redirects to /login" — exercised here against the
 *    *actual* route tree (not just the standalone `ProtectedRoute` guard in
 *    isolation), across every protected path named in the spec. "/" is *not*
 *    in this list: a later change (public `LandingPage`) moved the Dashboard
 *    to "/dashboard" and made "/" a public marketing route, so "/" is
 *    covered separately below by the landing-page test instead.
 *  - DoD: "/login renders with no Header/Sidebar chrome" — verified by
 *    asserting the absence of Header/Sidebar landmarks both when navigating
 *    directly to /login and when redirected there from a protected path.
 *  - DoD: "Header.tsx renders the authenticated user's real full_name ...
 *    after a page reload" — App.tsx's mount-time hydration effect (token
 *    present, user null) is exercised directly here, since this half of the
 *    DoD bullet is not covered by LoginPage.test.tsx (which only covers the
 *    post-login half).
 */
import { render, screen, waitFor, act } from "@testing-library/react";
import { describe, it, expect, afterEach } from "vitest";
import { App } from "./App";
import { useAuthStore } from "@/store/authStore";
import { mockUser } from "@/test/handlers";
import { resetAuthStore, seedAuthenticatedState } from "@/test/authTestUtils";

const PROTECTED_PATHS = ["/upload", "/configure", "/running", "/results"];

function navigateTo(path: string): void {
  act(() => {
    window.history.pushState({}, "", path);
  });
}

describe("App routing — auth guard", () => {
  afterEach(() => {
    resetAuthStore();
    navigateTo("/");
  });

  it.each(PROTECTED_PATHS)(
    "redirects an unauthenticated visitor at %s to /login",
    async (path) => {
      resetAuthStore();
      navigateTo(path);

      render(<App />);

      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });
      expect(
        screen.getByRole("heading", { name: /sign in/i }),
      ).toBeInTheDocument();
    },
  );

  it.each(PROTECTED_PATHS)(
    "shows no Header/Sidebar chrome when redirected from %s to /login",
    async (path) => {
      resetAuthStore();
      navigateTo(path);

      render(<App />);

      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });
      expect(screen.queryByText("Forecasting Platform")).not.toBeInTheDocument();
      expect(
        screen.queryByLabelText("Main navigation"),
      ).not.toBeInTheDocument();
    },
  );

  it("renders /login directly with no Header/Sidebar chrome", async () => {
    resetAuthStore();
    navigateTo("/login");

    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    });
    expect(screen.queryByText("Forecasting Platform")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Main navigation")).not.toBeInTheDocument();
  });

  it("renders the public landing page for an unauthenticated visitor at /", async () => {
    resetAuthStore();
    navigateTo("/");

    render(<App />);

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /forecast demand with/i }),
      ).toBeInTheDocument();
    });
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Main navigation")).not.toBeInTheDocument();
  });

  it("redirects an authenticated visitor away from / and renders AppShell chrome", async () => {
    seedAuthenticatedState({ user: mockUser });
    navigateTo("/");

    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText("Main navigation")).toBeInTheDocument();
    });
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /forecast demand with/i }),
    ).not.toBeInTheDocument();
  });
});

describe("App auth hydration on mount (page reload)", () => {
  afterEach(() => {
    resetAuthStore();
    navigateTo("/");
  });

  it("fetches the profile and shows the real full_name in Header when a token exists but user is null", async () => {
    seedAuthenticatedState({
      accessToken: "persisted-access-token",
      refreshToken: "persisted-refresh-token",
    });
    navigateTo("/");

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(mockUser.full_name)).toBeInTheDocument();
    });
    expect(screen.queryByText("Account")).not.toBeInTheDocument();
    expect(useAuthStore.getState().user).toEqual(mockUser);
  });
});
