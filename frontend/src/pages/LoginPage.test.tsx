import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, afterEach } from "vitest";
import { LoginPage } from "./LoginPage";
import { useAuthStore } from "@/store/authStore";
import { mockUser } from "@/test/handlers";
import { resetAuthStore } from "@/test/authTestUtils";

describe("LoginPage", () => {
  afterEach(() => {
    resetAuthStore();
  });

  it("calls setUser with the fetched profile after a successful login", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText(/email/i), "test@example.com");
    await user.type(screen.getByLabelText(/password/i), "password123");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(useAuthStore.getState().user).toEqual(mockUser);
    });
  });
});
