import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { BrandMark } from "./BrandMark";

describe("BrandMark", () => {
  it("renders an svg glyph", () => {
    const { container } = render(<BrandMark />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});
