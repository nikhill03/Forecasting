import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TERMINAL_STATES, useForecastProgress } from "@/hooks/useForecastJob";
import { useForecastStore } from "@/store/forecastStore";
import { formatRelativeTime } from "@/lib/format";
import type { ActiveRun } from "@/types/api";

interface ActiveRunRowProps {
  run: ActiveRun;
  onOpen: (jobId: string) => void;
}

function ActiveRunRow({ run, onOpen }: ActiveRunRowProps) {
  const queryClient = useQueryClient();
  // The database only records progress at start and finish, so the live
  // percentage comes from the same endpoint the Running page polls.
  const { data: progress } = useForecastProgress(run.job_id);

  const status = progress?.status ?? run.status;
  const isTerminal = TERMINAL_STATES.has(status);

  // Once this run finishes, refresh the summary: the row leaves this panel
  // and the run shows up in the totals, trend and wins.
  useEffect(() => {
    if (isTerminal) {
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
    }
  }, [isTerminal, queryClient]);

  const message =
    progress?.message || (status === "pending" ? "Queued" : "Starting…");

  return (
    <button
      type="button"
      onClick={() => onOpen(run.job_id)}
      className="flex w-full flex-col gap-2 px-5 py-3 text-left transition-colors hover:bg-bg-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="truncate text-sm font-medium text-text">
          {run.name ?? run.file_name ?? "Untitled run"}
        </span>
        <StatusBadge status={status} />
        <span className="ml-auto shrink-0 text-xs text-text-subtle">
          {formatRelativeTime(run.started_at ?? run.created_at)}
        </span>
        <ChevronRight
          className="h-4 w-4 shrink-0 text-text-subtle"
          aria-hidden="true"
        />
      </div>
      <ProgressBar value={progress?.progress ?? 0} label={message} />
    </button>
  );
}

interface ActiveRunsProps {
  runs: ActiveRun[];
}

export function ActiveRuns({ runs }: ActiveRunsProps) {
  const navigate = useNavigate();
  const setActiveJobId = useForecastStore((s) => s.setActiveJobId);

  if (runs.length === 0) return null;

  // RunningPage reads the job from the store, not the URL.
  const openRun = (jobId: string) => {
    setActiveJobId(jobId);
    navigate("/running");
  };

  return (
    <Card className="border-accent/30">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Loader2
            className="h-4 w-4 animate-spin text-accent"
            aria-hidden="true"
          />
          <CardTitle>In progress</CardTitle>
        </div>
        <span className="text-xs text-text-subtle">
          {runs.length} {runs.length === 1 ? "run" : "runs"}
        </span>
      </CardHeader>
      <CardContent className="px-0 py-0">
        <ul className="divide-y divide-border">
          {runs.map((run) => (
            <li key={run.job_id}>
              <ActiveRunRow run={run} onOpen={openRun} />
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
