import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FileText, Loader2, MoreVertical, Pencil } from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { forecastService } from "@/services/forecastService";
import { useForecastStore } from "@/store/forecastStore";
import { formatPercent, formatRelativeTime, formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ForecastJobSummary, JobStatus } from "@/types/api";

const STATUS_STYLES: Record<JobStatus, string> = {
  success: "bg-success/10 text-success",
  failed: "bg-danger/10 text-danger",
  running: "bg-accent/10 text-accent",
  pending: "bg-info/10 text-info",
  stopped: "bg-bg-raised text-text-muted",
};

interface JobHistoryRowProps {
  job: ForecastJobSummary;
  onViewResults: (jobId: string) => void;
}

function JobHistoryRow({ job, onViewResults }: JobHistoryRowProps) {
  const queryClient = useQueryClient();
  const [menuOpen, setMenuOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const displayName = job.name ?? job.file_name ?? "Untitled dataset";
  const [draftName, setDraftName] = useState(displayName);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isEditing) inputRef.current?.focus();
  }, [isEditing]);

  const renameMutation = useMutation({
    mutationFn: (name: string) => forecastService.renameJob(job.job_id, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["forecast-history"] });
    },
  });

  const commitRename = () => {
    const trimmed = draftName.trim();
    setIsEditing(false);
    if (trimmed && trimmed !== displayName) {
      renameMutation.mutate(trimmed);
    } else {
      setDraftName(displayName);
    }
  };

  const cancelRename = () => {
    setDraftName(displayName);
    setIsEditing(false);
  };

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 py-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            {isEditing ? (
              <input
                ref={inputRef}
                value={draftName}
                onChange={(e) => setDraftName(e.target.value)}
                onBlur={commitRename}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitRename();
                  if (e.key === "Escape") cancelRename();
                }}
                className="h-7 min-w-0 rounded-md border border-border bg-bg-raised px-2 text-sm text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            ) : (
              <span className="truncate text-sm font-medium text-text">
                {displayName}
              </span>
            )}
            <span
              className={cn(
                "shrink-0 rounded-full px-2 py-0.5 text-2xs font-medium capitalize",
                STATUS_STYLES[job.status],
              )}
            >
              {job.status}
            </span>
          </div>

          <div className="relative flex shrink-0 items-center gap-1">
            <span
              className="text-xs text-text-subtle"
              title={formatDate(job.created_at)}
            >
              {formatRelativeTime(job.created_at)}
            </span>
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              className="rounded-md p-1 text-text-muted hover:bg-bg-raised hover:text-text"
              aria-label="Job options"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
            >
              <MoreVertical className="h-4 w-4" aria-hidden="true" />
            </button>

            {menuOpen && (
              <div
                role="menu"
                className="absolute right-0 top-full z-10 mt-1 w-32 animate-slide-up rounded-md border border-border bg-bg-surface py-1 shadow-lg"
              >
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    setDraftName(displayName);
                    setIsEditing(true);
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-sm text-text-muted hover:bg-bg-raised hover:text-text"
                >
                  <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                  Rename
                </button>
              </div>
            )}
          </div>
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
            onClick={() => onViewResults(job.job_id)}
          >
            View results
            <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

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
    <div className="mx-auto max-w-4xl">
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
            <JobHistoryRow
              key={job.job_id}
              job={job}
              onViewResults={handleViewResults}
            />
          ))}
        </div>
      )}
    </div>
  );
}
