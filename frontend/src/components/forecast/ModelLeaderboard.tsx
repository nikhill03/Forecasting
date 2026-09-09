import { useId, useMemo, useState } from "react";
import { ChevronDown, Crown, AlertCircle, MinusCircle } from "lucide-react";
import { formatWmape, formatNumber, formatPercent } from "@/lib/format";
import { sortLeaderboard, type SortKey } from "@/lib/leaderboard";
import type { ModelRunResult } from "@/types/api";
import { cn } from "@/lib/utils";

// WMAPE leads, and is the default sort, because it is the only score every
// competitor has. composite_score is computed inside the univariate selection
// loop only — the multivariate candidates and Baseline_SMA are scored
// elsewhere and carry null — so defaulting to it would sink a strong
// multivariate model below a weaker univariate one purely for lack of a
// number. WMAPE is also the headline stat on the card above.
const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "wmape", label: "WMAPE" },
  { key: "composite_score", label: "Composite" },
  { key: "rmse", label: "RMSE" },
  { key: "mae", label: "MAE" },
];

function StatusMark({ status }: { status: string }) {
  if (status === "failed") {
    return (
      <span
        className="inline-flex items-center gap-1 text-danger"
        title="This model raised an error and produced no score"
      >
        <AlertCircle className="h-3 w-3" aria-hidden="true" />
        failed
      </span>
    );
  }
  if (status === "skipped") {
    return (
      <span
        className="inline-flex items-center gap-1 text-text-subtle"
        title="This model was not evaluated"
      >
        <MinusCircle className="h-3 w-3" aria-hidden="true" />
        skipped
      </span>
    );
  }
  return null;
}

interface ModelLeaderboardProps {
  models: ModelRunResult[];
}

export function ModelLeaderboard({ models }: ModelLeaderboardProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("wmape");
  const [direction, setDirection] = useState<"asc" | "desc">("asc");
  const panelId = useId();

  const sorted = useMemo(
    () => sortLeaderboard(models, sortKey, direction),
    [models, sortKey, direction],
  );

  // Runs from before F14 carry no leaderboard. Render nothing rather than an
  // empty table — the card's headline stats still stand on their own.
  if (models.length === 0) return null;

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setDirection("asc");
    }
  };

  return (
    <div className="mt-6 flex flex-col gap-3 border-t border-border pt-6">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        aria-expanded={isOpen}
        aria-controls={panelId}
        className="flex items-center gap-2 self-start text-sm font-semibold text-text hover:text-accent"
      >
        <ChevronDown
          className={cn(
            "h-4 w-4 transition-transform",
            isOpen && "rotate-180",
          )}
          aria-hidden="true"
        />
        All {models.length} models tried
      </button>

      {isOpen && (
        <div id={panelId} className="animate-slide-up overflow-x-auto">
          <table className="w-full min-w-[34rem] border-collapse text-xs">
            <caption className="sr-only">
              Every model evaluated for this metric, with its scores. Lower is
              better for every column.
            </caption>
            <thead>
              <tr className="border-b border-border text-left">
                <th
                  scope="col"
                  className="py-2 pr-3 font-medium text-text-subtle"
                >
                  Model
                </th>
                {COLUMNS.map((col) => {
                  const active = col.key === sortKey;
                  return (
                    <th
                      key={col.key}
                      scope="col"
                      aria-sort={
                        active
                          ? direction === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                      }
                      className="py-2 pr-3 text-right font-medium"
                    >
                      <button
                        type="button"
                        onClick={() => toggleSort(col.key)}
                        className={cn(
                          "hover:text-text",
                          active ? "text-accent" : "text-text-subtle",
                        )}
                      >
                        {col.label}
                        {active && (direction === "asc" ? " ↑" : " ↓")}
                      </button>
                    </th>
                  );
                })}
                <th
                  scope="col"
                  className="py-2 text-right font-medium text-text-subtle"
                >
                  Accuracy
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((model) => {
                const incomplete = model.status !== "completed";
                return (
                  <tr
                    key={`${model.model_name}-${model.stage}`}
                    className={cn(
                      "border-b border-border/50 last:border-0",
                      incomplete && "opacity-60",
                    )}
                  >
                    <td className="py-2 pr-3">
                      <span className="flex items-center gap-1.5 text-text">
                        {model.is_champion && (
                          <Crown
                            className="h-3 w-3 shrink-0 text-accent"
                            aria-label="Champion"
                          />
                        )}
                        {model.model_name}
                        <span className="text-2xs text-text-subtle">
                          {model.stage}
                        </span>
                      </span>
                      {incomplete && (
                        <span
                          className="mt-0.5 block text-2xs"
                          title={model.error_message ?? undefined}
                        >
                          <StatusMark status={model.status} />
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono tabular-nums text-text-muted">
                      {formatWmape(model.wmape)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono tabular-nums text-text-muted">
                      {formatWmape(model.composite_score)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono tabular-nums text-text-muted">
                      {formatNumber(model.rmse)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono tabular-nums text-text-muted">
                      {formatNumber(model.mae)}
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums text-text-muted">
                      {formatPercent(model.accuracy)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
