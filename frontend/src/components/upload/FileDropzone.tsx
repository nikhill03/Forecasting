import { useCallback, useRef, useState, type DragEvent } from "react";
import { Upload, FileSpreadsheet, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const ACCEPTED_TYPES = [".csv", ".xlsx", ".xls"];
const MAX_SIZE_MB = 50;

interface FileDropzoneProps {
  onFileSelect: (file: File) => void;
  isUploading?: boolean;
  error?: string | null;
}

export function FileDropzone({
  onFileSelect,
  isUploading = false,
  error = null,
}: FileDropzoneProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const validateAndSelect = useCallback(
    (file: File) => {
      const ext = "." + file.name.split(".").pop()?.toLowerCase();
      if (!ACCEPTED_TYPES.includes(ext)) {
        setLocalError(
          `File type not supported. Accepted: ${ACCEPTED_TYPES.join(", ")}`,
        );
        return;
      }
      if (file.size > MAX_SIZE_MB * 1024 * 1024) {
        setLocalError(`File exceeds ${MAX_SIZE_MB}MB limit.`);
        return;
      }
      setLocalError(null);
      onFileSelect(file);
    },
    [onFileSelect],
  );

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) validateAndSelect(file);
    },
    [validateAndSelect],
  );

  const displayError = error ?? localError;

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload dataset file. Drag and drop or press Enter to browse."
        aria-describedby={displayError ? "dropzone-error" : undefined}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-12 text-center transition-colors",
          isDragOver
            ? "border-accent bg-accent/5"
            : "border-border hover:border-border-strong",
          isUploading && "pointer-events-none opacity-60",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_TYPES.join(",")}
          className="sr-only"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) validateAndSelect(file);
          }}
          aria-hidden="true"
          tabIndex={-1}
        />

        <div className="rounded-full bg-bg-raised p-3">
          {isUploading ? (
            <FileSpreadsheet
              className="h-6 w-6 animate-pulse-slow text-accent"
              aria-hidden="true"
            />
          ) : (
            <Upload className="h-6 w-6 text-text-muted" aria-hidden="true" />
          )}
        </div>

        <div>
          <p className="text-sm font-medium text-text">
            {isUploading
              ? "Uploading…"
              : "Drop your dataset here, or click to browse"}
          </p>
          <p className="mt-1 text-xs text-text-muted">
            CSV or Excel · up to {MAX_SIZE_MB}MB · must include a date column
          </p>
        </div>
      </div>

      {displayError && (
        <div
          id="dropzone-error"
          role="alert"
          className="mt-2 flex items-center gap-1.5 text-sm text-danger"
        >
          <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          {displayError}
        </div>
      )}
    </div>
  );
}