import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { useForecastStore } from "@/store/forecastStore";
import { formatDuration, formatRelativeTime } from "@/lib/format";
import type { RunDuration } from "@/types/api";

interface RunTimeCardProps {
  medianSeconds: number | null;
  // Slowest first; every entry is a successful run.
  slowest: RunDuration[];
}

export function RunTimeCard({ medianSeconds, slowest }: RunTimeCardProps) {
  const navigate = useNavigate();
  const setActiveJobId = useForecastStore((s) => s.setActiveJobId);

  const openResults = (jobId: string) => {
    setActiveJobId(jobId);
    navigate("/results");
  };

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Run time</CardTitle>
          <p className="mt-0.5 text-xs text-text-subtle">
            Median across your recent completed runs
          </p>
        </div>
      </CardHeader>
      <CardContent>
        {medianSeconds === null ? (
          <p className="text-sm text-text-muted">
            No completed runs with timing yet.
          </p>
        ) : (
          <>
            <p className="text-2xl font-semibold text-text">
              {formatDuration(medianSeconds)}
            </p>

            {slowest.length > 0 && (
              <>
                <p className="mb-1 mt-4 text-2xs uppercase tracking-[0.08em] text-text-subtle">
                  Slowest
                </p>
                <ul className="-mx-2">
                  {slowest.map((run) => (
                    <li key={run.job_id}>
                      <button
                        type="button"
                        onClick={() => openResults(run.job_id)}
                        className="flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-bg-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      >
                        <span className="min-w-0 flex-1 truncate text-text-muted">
                          {run.name ?? run.file_name ?? "Untitled run"}
                        </span>
                        <span className="shrink-0 text-xs text-text-subtle">
                          {formatRelativeTime(run.created_at)}
                        </span>
                        <span className="w-16 shrink-0 text-right font-mono text-xs tabular-nums text-text">
                          {formatDuration(run.duration_seconds)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
