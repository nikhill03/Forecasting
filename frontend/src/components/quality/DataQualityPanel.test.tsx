import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataQualityPanel } from "./DataQualityPanel";
import {
  mockBlockingReport,
  mockQualityReport,
  mockWarningReport,
} from "@/test/handlers";

describe("DataQualityPanel", () => {
  it("separates blocking problems from warnings", () => {
    render(<DataQualityPanel report={mockBlockingReport} />);

    const blocking = screen.getByRole("region", { name: /must fix before running/i });
    expect(within(blocking).getByText(/20 usable data points/)).toBeInTheDocument();
    expect(within(blocking).queryByText(/negative values/)).not.toBeInTheDocument();

    const warnings = screen.getByRole("region", { name: /worth knowing/i });
    expect(within(warnings).getByText(/negative values/)).toBeInTheDocument();
    expect(within(warnings).queryByText(/usable data points/)).not.toBeInTheDocument();
  });

  it("doesn't show split or horizon numbers for a blocked series", () => {
    const blocked = {
      ...mockBlockingReport,
      series: mockBlockingReport.series.map((s) => ({
        ...s,
        test_split_size: 0,
        effective_horizon: 0,
      })),
    };
    render(<DataQualityPanel report={blocked} />);
    expect(screen.getByText("Usable points")).toBeInTheDocument();
    expect(screen.queryByText("Held out for testing")).not.toBeInTheDocument();
  });

  it("shows only warnings when nothing blocks", () => {
    render(<DataQualityPanel report={mockWarningReport} />);

    expect(screen.queryByRole("region", { name: /must fix/i })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: /worth knowing/i })).toBeInTheDocument();
  });

  it("says so when the data is clean, and still shows what the run will use", () => {
    render(<DataQualityPanel report={mockQualityReport} />);

    expect(screen.getByText("No issues found in 1 series.")).toBeInTheDocument();
    expect(screen.getByText("Held out for testing")).toBeInTheDocument();
    expect(screen.getByText("30 points")).toBeInTheDocument();
    expect(screen.getByText("Daily")).toBeInTheDocument();
  });

  it("explains a failed check without implying the run is blocked", () => {
    render(<DataQualityPanel report={undefined} isError />);
    expect(screen.getByText(/you can still run the forecast/i)).toBeInTheDocument();
  });

  it("keeps the previous report visible while updating", () => {
    render(<DataQualityPanel report={mockWarningReport} isFetching />);
    expect(screen.getByRole("status")).toHaveTextContent("Updating…");
    expect(screen.getByRole("region", { name: /worth knowing/i })).toBeInTheDocument();
  });
});
