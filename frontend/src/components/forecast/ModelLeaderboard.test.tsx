import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect } from "vitest";

import { ModelLeaderboard } from "./ModelLeaderboard";
import { sortLeaderboard } from "@/lib/leaderboard";
import type { ModelRunResult } from "@/types/api";

function model(
  name: string,
  over: Partial<ModelRunResult> = {},
): ModelRunResult {
  return {
    model_name: name,
    stage: "Univariate",
    wmape: 0.1,
    mae: 10,
    mape: 5,
    rmse: 20,
    accuracy: 90,
    composite_score: 0.2,
    is_champion: false,
    status: "completed",
    error_message: null,
    ...over,
  };
}

const FIELD: ModelRunResult[] = [
  model("Prophet", { is_champion: true, composite_score: 0.15, wmape: 0.07 }),
  model("TBATS", { composite_score: 0.31, wmape: 0.19 }),
  model("Ridge", { composite_score: 0.22, wmape: 0.12, stage: "Multivariate" }),
];

// The component renders nothing until opened — every test needs the panel.
async function openPanel(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /models tried/i }));
}

function rowNames(): string[] {
  const rows = screen.getAllByRole("row").slice(1); // drop the header row
  return rows.map((r) => within(r).getAllByRole("cell")[0]?.textContent ?? "");
}

describe("sortLeaderboard", () => {
  it("pins the champion first regardless of sort key or direction", () => {
    // Prophet is champion but not last by every metric — the point is that
    // the headline the card states can never be buried by a sort.
    const worstChampion = [
      model("Prophet", { is_champion: true, composite_score: 9.9 }),
      model("TBATS", { composite_score: 0.1 }),
    ];
    for (const dir of ["asc", "desc"] as const) {
      const sorted = sortLeaderboard(worstChampion, "composite_score", dir);
      expect(sorted[0]?.model_name).toBe("Prophet");
    }
  });

  it("orders the rest ascending by the chosen key", () => {
    const sorted = sortLeaderboard(FIELD, "composite_score", "asc");
    expect(sorted.map((m) => m.model_name)).toEqual([
      "Prophet",
      "Ridge",
      "TBATS",
    ]);
  });

  it("reverses the non-champion rows when descending", () => {
    const sorted = sortLeaderboard(FIELD, "composite_score", "desc");
    expect(sorted.map((m) => m.model_name)).toEqual([
      "Prophet",
      "TBATS",
      "Ridge",
    ]);
  });

  it("sorts on a different key independently", () => {
    const sorted = sortLeaderboard(FIELD, "rmse", "asc");
    expect(sorted[0]?.model_name).toBe("Prophet");
  });

  it("sinks scoreless rows to the bottom rather than treating them as zero", () => {
    // A failed model has no score, not a perfect one — it must never sort
    // above a model that actually ran.
    const withFailure = [
      model("Prophet", { is_champion: true, composite_score: 0.5 }),
      model("TBATS", { composite_score: null, status: "failed" }),
      model("Ridge", { composite_score: 0.9 }),
    ];
    const sorted = sortLeaderboard(withFailure, "composite_score", "asc");
    expect(sorted.map((m) => m.model_name)).toEqual([
      "Prophet",
      "Ridge",
      "TBATS",
    ]);
  });

  it("breaks ties by model name for stable output", () => {
    const tied = [model("Zeta", { composite_score: 1 }), model("Alpha", { composite_score: 1 })];
    expect(sortLeaderboard(tied, "composite_score", "asc")[0]?.model_name).toBe(
      "Alpha",
    );
  });

  it("does not mutate the input array", () => {
    const input = [...FIELD];
    sortLeaderboard(input, "wmape", "desc");
    expect(input.map((m) => m.model_name)).toEqual(FIELD.map((m) => m.model_name));
  });
});

describe("ModelLeaderboard", () => {
  it("renders nothing when there is no leaderboard", () => {
    // Runs from before F14 carry an empty array.
    const { container } = render(<ModelLeaderboard models={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is collapsed by default and names the number of models", () => {
    render(<ModelLeaderboard models={FIELD} />);
    const toggle = screen.getByRole("button", { name: /all 3 models tried/i });

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("reveals every model on expand", async () => {
    const user = userEvent.setup();
    render(<ModelLeaderboard models={FIELD} />);
    await openPanel(user);

    expect(screen.getByRole("table")).toBeInTheDocument();
    for (const name of ["Prophet", "TBATS", "Ridge"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("marks the champion and shows it first", async () => {
    const user = userEvent.setup();
    render(<ModelLeaderboard models={FIELD} />);
    await openPanel(user);

    expect(screen.getByLabelText("Champion")).toBeInTheDocument();
    expect(rowNames()[0]).toContain("Prophet");
  });

  it("defaults to WMAPE, the only score every competitor has", async () => {
    const user = userEvent.setup();
    render(<ModelLeaderboard models={FIELD} />);
    await openPanel(user);

    expect(screen.getByRole("columnheader", { name: /wmape/i })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    expect(rowNames().map((n) => n.replace(/Univariate|Multivariate/, ""))).toEqual(
      ["Prophet", "Ridge", "TBATS"],
    );
  });

  it("re-sorts when a column header is clicked", async () => {
    const user = userEvent.setup();
    render(<ModelLeaderboard models={FIELD} />);
    await openPanel(user);

    // Same key again flips direction; champion stays pinned.
    await user.click(screen.getByRole("button", { name: /wmape/i }));
    const flipped = rowNames().map((n) =>
      n.replace(/Univariate|Multivariate/, ""),
    );
    expect(flipped[0]).toBe("Prophet");
    expect(flipped).toEqual(["Prophet", "TBATS", "Ridge"]);
  });

  it("keeps rows without a composite score visible when sorting by it", async () => {
    // Multivariate candidates and Baseline_SMA carry a null composite_score
    // in real runs — they must sink, not vanish.
    const user = userEvent.setup();
    render(
      <ModelLeaderboard
        models={[
          model("ExtraTrees", { is_champion: true, composite_score: null }),
          model("Prophet", { composite_score: 0.02 }),
          model("Ridge", { composite_score: null, stage: "Multivariate" }),
        ]}
      />,
    );
    await openPanel(user);
    await user.click(screen.getByRole("button", { name: /composite/i }));

    const names = rowNames().map((n) => n.replace(/Univariate|Multivariate/, ""));
    expect(names).toHaveLength(3);
    expect(names[0]).toBe("ExtraTrees");
    expect(names).toContain("Ridge");
  });

  it("exposes sort state to assistive tech via aria-sort", async () => {
    const user = userEvent.setup();
    render(<ModelLeaderboard models={FIELD} />);
    await openPanel(user);

    const wmape = screen.getByRole("columnheader", { name: /wmape/i });
    expect(wmape).toHaveAttribute("aria-sort", "ascending");

    await user.click(screen.getByRole("button", { name: /composite/i }));
    expect(
      screen.getByRole("columnheader", { name: /composite/i }),
    ).toHaveAttribute("aria-sort", "ascending");
    expect(wmape).toHaveAttribute("aria-sort", "none");
  });

  it("shows failed and skipped models rather than omitting them", async () => {
    // The whole point of the feature: a user must be able to tell "didn't
    // win" from "didn't finish".
    const user = userEvent.setup();
    render(
      <ModelLeaderboard
        models={[
          model("Prophet", { is_champion: true }),
          model("TBATS", {
            status: "failed",
            error_message: "soft time limit exceeded",
            wmape: null,
            composite_score: null,
          }),
          model("Croston", {
            status: "skipped",
            error_message: "Insufficient test overlap",
            wmape: null,
          }),
        ]}
      />,
    );
    await openPanel(user);

    expect(screen.getByText("TBATS")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("skipped")).toBeInTheDocument();
  });

  it("renders an em dash for a missing score instead of a zero", async () => {
    const user = userEvent.setup();
    render(
      <ModelLeaderboard
        models={[model("TBATS", { status: "failed", wmape: null, rmse: null })]}
      />,
    );
    await openPanel(user);

    const row = screen.getAllByRole("row")[1];
    expect(within(row as HTMLElement).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("collapses again on a second click", async () => {
    const user = userEvent.setup();
    render(<ModelLeaderboard models={FIELD} />);
    await openPanel(user);
    expect(screen.getByRole("table")).toBeInTheDocument();

    await openPanel(user);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
