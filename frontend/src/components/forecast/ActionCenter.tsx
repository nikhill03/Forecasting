import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, RotateCcw, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { forecastService } from "@/services/forecastService";
import { ApiError } from "@/services/client";
import type { ForecastRecord } from "@/types/api";

interface ActionCenterProps {
  jobId: string;
  sheetName: string;
  metricName: string;
  onRecordsChange: (records: ForecastRecord[]) => void;
}

export function ActionCenter({
  jobId,
  sheetName,
  metricName,
  onRecordsChange,
}: ActionCenterProps) {
  const queryClient = useQueryClient();
  const [instruction, setInstruction] = useState("");
  const [error, setError] = useState<string | null>(null);

  const queryKey = ["action-center", jobId, sheetName, metricName];

  const { data } = useQuery({
    queryKey,
    queryFn: () => forecastService.getActionState(jobId, sheetName, metricName),
  });

  useEffect(() => {
    if (data) onRecordsChange(data.records);
    // onRecordsChange identity isn't expected to change per mount — only
    // re-sync the chart when the server state itself changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const applyMutation = useMutation({
    mutationFn: (text: string) =>
      forecastService.applyAction(jobId, sheetName, metricName, text),
    onSuccess: (result) => {
      setError(null);
      setInstruction("");
      queryClient.setQueryData(queryKey, result);
      onRecordsChange(result.records);
    },
    onError: (err) => {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't apply that instruction. Try again.",
      );
    },
  });

  const revertMutation = useMutation({
    mutationFn: () => forecastService.revertAction(jobId, sheetName, metricName),
    onSuccess: (result) => {
      setError(null);
      queryClient.setQueryData(queryKey, result);
      onRecordsChange(result.records);
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Couldn't revert.");
    },
  });

  const downloadMutation = useMutation({
    mutationFn: () => forecastService.exportCsv(jobId, sheetName, metricName),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${sheetName}_${metricName}_forecast.csv`;
      link.click();
      URL.revokeObjectURL(url);
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Couldn't download the CSV.");
    },
  });

  const edits = data?.edits ?? [];

  return (
    <div className="flex w-full shrink-0 flex-col gap-3 lg:w-72">
      <div>
        <h3 className="text-sm font-semibold text-text">AI Action Center</h3>
        <p className="mt-1 text-xs text-text-muted">
          Describe a change in plain language.
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          const trimmed = instruction.trim();
          if (trimmed) applyMutation.mutate(trimmed);
        }}
        className="flex flex-col gap-2"
      >
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          rows={3}
          placeholder='e.g. "cap the forecast at 500"'
          className="w-full resize-none rounded-md border border-border bg-bg-raised px-3 py-2 text-sm text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        />
        <Button
          type="submit"
          size="sm"
          isLoading={applyMutation.isPending}
          disabled={!instruction.trim()}
        >
          <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
          Apply
        </Button>
      </form>

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger/10 px-2.5 py-2 text-xs text-danger"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      {edits.length > 0 && (
        <Button
          variant="secondary"
          size="sm"
          onClick={() => revertMutation.mutate()}
          isLoading={revertMutation.isPending}
        >
          <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
          Revert last edit
        </Button>
      )}

      {edits.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {edits.map((edit) => (
            <li
              key={edit.id}
              className="rounded-md bg-bg-raised px-2.5 py-1.5 text-xs text-text-muted"
            >
              {edit.instruction_text}
            </li>
          ))}
        </ul>
      )}

      <Button
        variant="secondary"
        size="sm"
        onClick={() => downloadMutation.mutate()}
        isLoading={downloadMutation.isPending}
      >
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        Download CSV
      </Button>
    </div>
  );
}
