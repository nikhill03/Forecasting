import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DemandQuadrant } from "./DemandQuadrant";

describe("DemandQuadrant", () => {
  it("renders the four demand class labels", () => {
    render(<DemandQuadrant />);
    expect(screen.getByRole("img", { name: /demand series classified/i })).toBeInTheDocument();
  });

  it("renders the landing-page illustration unchanged when no counts are given", () => {
    const { container } = render(<DemandQuadrant />);

    expect(container.querySelectorAll("circle")).toHaveLength(14);
    expect(screen.queryByText("series")).not.toBeInTheDocument();
  });

  it("shows real counts instead of illustrative dots when counts are given", () => {
    const { container } = render(
      <DemandQuadrant counts={{ Smooth: 7, Erratic: 2, Intermittent: 0, Lumpy: 1 }} />,
    );

    expect(container.querySelectorAll("circle")).toHaveLength(0);
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: /smooth 7, erratic 2, intermittent 0, lumpy 1/i,
      }),
    ).toBeInTheDocument();
  });

  it("treats a missing quadrant as zero", () => {
    render(<DemandQuadrant counts={{ Smooth: 3 }} />);
    expect(
      screen.getByRole("img", { name: /smooth 3, erratic 0, intermittent 0, lumpy 0/i }),
    ).toBeInTheDocument();
  });
});
