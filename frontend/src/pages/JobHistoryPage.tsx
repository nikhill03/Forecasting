import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, FileText, Loader2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { forecastService } from "@/services/forecastService";
import { useForecastStore } from "@/store/forecastStore";
import { formatPercent, formatRelativeTime, formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { JobStatus } from "@/types/api";

const STATUS_STYLES: Record<JobStatus, string> = {
  success: "bg-success/10 text-success",
  failed: "bg-danger/10 text-danger",
  running: "bg-accent/10 text-accent",
  pending: "bg-info/10 text-info",
  stopped: "bg-bg-raised text-text-muted",
};

export function JobHistoryPage() {
  const navigate = useNavigate();
  const setActiveJobId = useForecastStore((s) => s.setActiveJobId);

  const { data, isLoading } = useQuery({
    queryKey: ["forecast-history"],
    queryFn: () => forecastService.listJobs(50, 0),
  });

  const handleViewResults = (jobId: string) => {
    setActiveJobId(jobId);
    navigate("/results");
  };

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center text-text-muted">
        <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
      </div>
    );
  }

  const jobs = data?.jobs ?? [];

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-text">Job history</h1>
        <p className="mt-1 text-sm text-text-muted">Your past forecast runs.</p>
      </div>

      {jobs.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <FileText className="h-8 w-8 text-text-subtle" aria-hidden="true" />
            <p className="text-sm text-text-muted">No forecasts yet.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {jobs.map((job) => (
            <Card key={job.job_id}>
              <CardContent className="flex flex-col gap-3 py-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-text">
                      {job.file_name ?? "Untitled dataset"}
                    </span>
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-2xs font-medium capitalize",
                        STATUS_STYLES[job.status],
                      )}
                    >
                      {job.status}
                    </span>
                  </div>
                  <span
                    className="text-xs text-text-subtle"
                    title={formatDate(job.created_at)}
                  >
                    {formatRelativeTime(job.created_at)}
                  </span>
                </div>

                {job.metrics.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {job.metrics.map((m) => (
                      <span
                        key={`${m.sheet_name ?? ""}-${m.metric_name ?? ""}`}
                        className="rounded-full bg-bg-raised px-2.5 py-1 text-2xs text-text-muted"
                      >
                        {m.metric_name}: {m.model_name ?? "—"}
                        {m.wmape !== null && ` (${formatPercent(m.wmape * 100)})`}
                      </span>
                    ))}
                  </div>
                )}

                {job.status === "failed" && job.error && (
                  <p className="text-xs text-danger">{job.error}</p>
                )}

                {job.status === "success" && (
                  <Button
                    variant="secondary"
                    size="sm"
                    className="self-end"
                    onClick={() => handleViewResults(job.job_id)}
                  >
                    View results
                    <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
                  </Button>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
