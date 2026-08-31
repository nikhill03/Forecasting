import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DemandQuadrant } from "./DemandQuadrant";

describe("DemandQuadrant", () => {
  it("renders the four demand class labels", () => {
    render(<DemandQuadrant />);
    expect(screen.getByRole("img", { name: /demand series classified/i })).toBeInTheDocument();
  });
});
