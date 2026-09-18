import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DataQualityCaveats } from "./DataQualityCaveats";
import { mockQualityReport, mockWarningReport } from "@/test/handlers";

describe("DataQualityCaveats", () => {
  it("explains why a run from before data checks has none", () => {
    render(<DataQualityCaveats report={null} />);
    expect(screen.getByText(/created before data checks were added/i)).toBeInTheDocument();
  });

  it("says there were no warnings for a clean run", () => {
    render(<DataQualityCaveats report={mockQualityReport} />);
    expect(screen.getByText("No data warnings for this run.")).toBeInTheDocument();
  });

  it("collapses warnings behind a count, and expands on click", async () => {
    const user = userEvent.setup();
    render(<DataQualityCaveats report={mockWarningReport} />);

    const toggle = screen.getByRole("button", { name: /built on data with 1 warning/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/duplicate dates/)).not.toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/duplicate dates/)).toBeInTheDocument();
  });
});
