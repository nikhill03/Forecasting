import { Link, useNavigate } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useForecastStore } from "@/store/forecastStore";
import {
  formatDate,
  formatFractionAsPercent,
  formatRelativeTime,
} from "@/lib/format";
import type { RecentRun } from "@/types/api";

function runTitle(run: RecentRun): string {
  return run.name ?? run.file_name ?? "Untitled run";
}

// A run with several metrics has a winner per metric; name the first and say
// how many more there are rather than pretend there was one winner.
function championLabel(run: RecentRun): string | null {
  if (!run.champion_model) return null;
  return run.metric_count > 1
    ? `${run.champion_model} +${run.metric_count - 1}`
    : run.champion_model;
}

function RunSummary({ run }: { run: RecentRun }) {
  const champion = championLabel(run);

  return (
    <>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-text">
            {runTitle(run)}
          </span>
          <StatusBadge status={run.status} />
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-text-subtle">
          <span title={formatDate(run.created_at)}>
            {formatRelativeTime(run.created_at)}
          </span>
          {champion && (
            <>
              <span aria-hidden="true">·</span>
              <span className="truncate text-text-muted">{champion}</span>
            </>
          )}
        </div>
      </div>
      {run.wmape !== null && (
        <div className="shrink-0 text-right">
          <div className="font-mono text-sm tabular-nums text-text">
            {formatFractionAsPercent(run.wmape)}
          </div>
          <div className="text-2xs uppercase tracking-[0.08em] text-text-subtle">
            WMAPE
          </div>
        </div>
      )}
    </>
  );
}

interface RecentRunsProps {
  runs: RecentRun[];
}

export function RecentRuns({ runs }: RecentRunsProps) {
  const navigate = useNavigate();
  const setActiveJobId = useForecastStore((s) => s.setActiveJobId);

  // ResultsPage reads the job from the store, not the URL, so opening a run
  // works the same way it does from JobHistoryPage.
  const openResults = (jobId: string) => {
    setActiveJobId(jobId);
    navigate("/results");
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent runs</CardTitle>
        <Link
          to="/history"
          className="text-xs font-medium text-text-muted hover:text-accent"
        >
          View all
        </Link>
      </CardHeader>
      <CardContent className="px-0 py-0">
        <ul className="divide-y divide-border">
          {runs.map((run) => (
            <li key={run.job_id}>
              {run.status === "success" ? (
                <button
                  type="button"
                  onClick={() => openResults(run.job_id)}
                  className="flex w-full items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-bg-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
                >
                  <RunSummary run={run} />
                  <ChevronRight
                    className="h-4 w-4 shrink-0 text-text-subtle"
                    aria-hidden="true"
                  />
                </button>
              ) : (
                // Only successful runs have results to open.
                <div className="flex items-center gap-3 px-5 py-3">
                  <RunSummary run={run} />
                  <span className="h-4 w-4 shrink-0" aria-hidden="true" />
                </div>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
