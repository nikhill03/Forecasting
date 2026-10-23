import { useMutation } from "@tanstack/react-query";
import { FileDropzone } from "@/components/upload/FileDropzone";
import { Button } from "@/components/ui/Button";
import {
  useEvaluateRealized,
  useRealizedCandidates,
} from "@/hooks/useRealizedAccuracy";
import { ApiError } from "@/services/client";
import { uploadService } from "@/services/uploadService";
import { formatDate, formatRelativeTime } from "@/lib/format";

interface CheckActualsDialogProps {
  jobId: string;
  forecastStart: string | null;
  forecastEnd: string | null;
  panelId: string;
  onClose: () => void;
}

// An inline panel rather than a modal: the app has no dialog primitive, and
// this is a small choice (pick a file or add one) that reads fine in place.
export function CheckActualsDialog({
  jobId,
  forecastStart,
  forecastEnd,
  panelId,
  onClose,
}: CheckActualsDialogProps) {
  const candidates = useRealizedCandidates(jobId, true);
  const { evaluate, isEvaluating, error: evaluateError, reset } =
    useEvaluateRealized(jobId);

  // Not useUpload(): that hook also makes the file the app's "current upload",
  // which would swap the dataset out from under the user's next forecast.
  const upload = useMutation({
    mutationFn: (file: File) => uploadService.uploadFile(file),
    onSuccess: (uploaded) => evaluate(uploaded.upload_id, { onSuccess: onClose }),
  });

  const busy = upload.isPending || isEvaluating;
  const uploadError =
    upload.error instanceof ApiError
      ? upload.error.message
      : upload.error
        ? "The file could not be uploaded. Try again."
        : null;
  const error = uploadError ?? evaluateError;

  const chooseUpload = (uploadId: string) => {
    upload.reset();
    reset();
    evaluate(uploadId, { onSuccess: onClose });
  };

  const needs =
    forecastStart && forecastEnd
      ? `${formatDate(forecastStart)} to ${formatDate(forecastEnd)}`
      : "the forecast period";

  return (
    <section
      id={panelId}
      aria-label="Check against newer data"
      className="flex animate-slide-up flex-col gap-4 rounded-md border border-border bg-bg-raised p-4"
    >
      <p className="text-sm text-text-muted">
        Pick a file that has actual values for {needs}. Dates are matched
        exactly, so the file needs the same date column and metric name.
      </p>

      {candidates.isLoading && (
        <p className="text-xs text-text-subtle">Looking through your uploads…</p>
      )}

      {candidates.isError && (
        <p className="text-xs text-danger" role="alert">
          Could not load your uploads. You can still upload a file below.
        </p>
      )}

      {candidates.data && candidates.data.length > 0 && (
        <ul className="flex flex-col divide-y divide-border/60" aria-label="Your later uploads">
          {candidates.data.map((candidate) => (
            <li
              key={candidate.upload_id}
              className="flex items-center justify-between gap-3 py-2"
            >
              <span className="min-w-0">
                <span className="block truncate text-sm text-text">
                  {candidate.file_name}
                </span>
                <span className="text-2xs text-text-subtle">
                  Uploaded {formatRelativeTime(candidate.created_at)}
                </span>
              </span>
              <Button
                variant="secondary"
                size="sm"
                disabled={busy}
                aria-label={`Use ${candidate.file_name}`}
                onClick={() => chooseUpload(candidate.upload_id)}
              >
                Use this file
              </Button>
            </li>
          ))}
        </ul>
      )}

      {candidates.data && candidates.data.length === 0 && (
        <p className="text-xs text-text-subtle">
          None of your later uploads include this metric.
        </p>
      )}

      <FileDropzone
        onFileSelect={(file) => {
          reset();
          upload.mutate(file);
        }}
        isUploading={busy}
        error={error}
      />

      <div className="flex justify-end">
        <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
      </div>
    </section>
  );
}
