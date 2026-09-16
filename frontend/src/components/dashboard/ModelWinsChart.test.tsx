import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ModelWinsChart } from "./ModelWinsChart";
import { mockDashboardSummary } from "@/test/handlers";

const WINS = mockDashboardSummary.model_wins; // Prophet 7, then three with 1

function tableRows() {
  // The visible bars are aria-hidden; the table is what assistive tech reads.
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell").map((c) => c.textContent));
}

describe("ModelWinsChart", () => {
  it("explains itself when nothing has won yet", () => {
    render(<ModelWinsChart wins={[]} />);
    expect(screen.getByText(/no winning models recorded yet/i)).toBeInTheDocument();
  });

  it("lists every model with its wins and share, most wins first", () => {
    render(<ModelWinsChart wins={WINS} />);

    expect(tableRows()).toEqual([
      ["Prophet", "7", "70%"],
      ["Baseline_SMA", "1", "10%"],
      ["Ensemble[Huber+Ridge]", "1", "10%"],
      ["Theta", "1", "10%"],
    ]);
  });

  it("folds a long tail of models into Other", () => {
    const many = Array.from({ length: 8 }, (_, i) => ({
      model_name: `Model${i}`,
      wins: 8 - i,
    }));
    render(<ModelWinsChart wins={many} />);

    const rows = tableRows();
    expect(rows).toHaveLength(6);
    expect(rows[5]).toEqual(["Other (3)", "6", "17%"]);
  });

  it("shows the share on hover", async () => {
    const user = userEvent.setup();
    const { container } = render(<ModelWinsChart wins={WINS} />);

    const firstBar = container.querySelector("li > div");
    expect(firstBar).not.toBeNull();
    if (firstBar) await user.hover(firstBar);

    expect(screen.getByText("Prophet won 7 of 10 (70%)")).toBeInTheDocument();
  });
});
