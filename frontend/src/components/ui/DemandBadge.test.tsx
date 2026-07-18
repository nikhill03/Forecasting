import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DemandBadge } from "./DemandBadge";

describe("DemandBadge", () => {
  it("renders the demand type label", () => {
    render(<DemandBadge type="Smooth" />);
    expect(screen.getByText("Smooth")).toBeInTheDocument();
  });

  it.each([
    ["Smooth"],
    ["Erratic"],
    ["Intermittent"],
    ["Lumpy"],
  ] as const)("renders distinguishable icon for %s type", (type) => {
    render(<DemandBadge type={type} />);
    const badge = screen.getByRole("img");
    expect(badge).toHaveAccessibleName(expect.stringContaining(type));
  });

  it("includes ADI and CV2 in accessible description when provided", () => {
    render(<DemandBadge type="Lumpy" adi={2.5} cv2={0.6} />);
    const badge = screen.getByRole("img");
    expect(badge.getAttribute("aria-label")).toContain("2.50");
    expect(badge.getAttribute("aria-label")).toContain("0.60");
  });

  it("hides label visually when showLabel is false but keeps aria-label", () => {
    render(<DemandBadge type="Erratic" showLabel={false} />);
    expect(screen.queryByText("Erratic")).not.toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute(
      "aria-label",
      expect.stringContaining("Erratic"),
    );
  });

  it("icon paths differ between all four demand types (no color-only distinction)", () => {
    const { container: c1 } = render(<DemandBadge type="Smooth" />);
    const { container: c2 } = render(<DemandBadge type="Erratic" />);
    const { container: c3 } = render(<DemandBadge type="Intermittent" />);
    const { container: c4 } = render(<DemandBadge type="Lumpy" />);

    const path1 = c1.querySelector("path")?.getAttribute("d");
    const path2 = c2.querySelector("path")?.getAttribute("d");
    const path3 = c3.querySelector("path")?.getAttribute("d");
    const path4 = c4.querySelector("path")?.getAttribute("d");

    const paths = [path1, path2, path3, path4];
    const uniquePaths = new Set(paths);
    expect(uniquePaths.size).toBe(4);
  });
});