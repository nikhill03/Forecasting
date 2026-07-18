import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { Button } from "./Button";

describe("Button", () => {
  it("renders children text", () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole("button", { name: "Click me" })).toBeInTheDocument();
  });

  it("calls onClick when clicked", async () => {
    const handleClick = vi.fn();
    const user = userEvent.setup();
    render(<Button onClick={handleClick}>Submit</Button>);

    await user.click(screen.getByRole("button"));
    expect(handleClick).toHaveBeenCalledOnce();
  });

  it("is disabled when isLoading is true", () => {
    render(<Button isLoading>Submit</Button>);
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("shows loadingText when provided and loading", () => {
    render(
      <Button isLoading loadingText="Saving…">
        Save
      </Button>,
    );
    expect(screen.getByText("Saving…")).toBeInTheDocument();
    expect(screen.queryByText("Save")).not.toBeInTheDocument();
  });

  it("sets aria-busy when loading", () => {
    render(<Button isLoading>Submit</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("aria-busy", "true");
  });

  it("does not call onClick when disabled", async () => {
    const handleClick = vi.fn();
    const user = userEvent.setup();
    render(
      <Button disabled onClick={handleClick}>
        Submit
      </Button>,
    );
    await user.click(screen.getByRole("button"));
    expect(handleClick).not.toHaveBeenCalled();
  });

  it("is keyboard accessible (Enter triggers click)", async () => {
    const handleClick = vi.fn();
    const user = userEvent.setup();
    render(<Button onClick={handleClick}>Submit</Button>);

    const button = screen.getByRole("button");
    button.focus();
    await user.keyboard("{Enter}");
    expect(handleClick).toHaveBeenCalled();
  });
});