import { Check, Loader2, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const STAGE_LABELS = [
  "Preparing data",
  "Engineering features",
  "Univariate models",
  "Multivariate models",
  "Finalizing",
] as const;

interface PipelineStepperProps {
  message?: string;
  isFailed?: boolean;
}

/** Backend messages look like "Stage 3/5: Running Univariate Models..." —
 * degrades gracefully to "not started" (-1) for any message that doesn't
 * match (e.g. "Initializing forecasting engine...", "Job queued"), so the
 * stepper never lies, it just shows less. */
function parseStageIndex(message?: string): number {
  const match = message?.match(/^Stage (\d)\/5:/);
  const stage = match?.[1] ? Number(match[1]) : NaN;
  return Number.isFinite(stage) ? stage - 1 : -1;
}

export function PipelineStepper({ message, isFailed = false }: PipelineStepperProps) {
  const currentIndex = parseStageIndex(message);

  return (
    <div className="flex w-full items-start" role="list" aria-label="Pipeline stages">
      {STAGE_LABELS.map((label, index) => {
        const isDone = !isFailed && currentIndex > index;
        const isActive = currentIndex === index;
        const isErrored = isFailed && isActive;
        const isConnectorFilled = !isFailed && currentIndex > index;

        return (
          <div key={label} role="listitem" className="flex flex-1 items-center last:flex-none">
            <div className="flex flex-col items-center gap-1.5">
              <div
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-2xs font-medium",
                  isErrored && "border-danger bg-danger/10 text-danger",
                  !isErrored && isDone && "border-accent bg-accent/10 text-accent",
                  !isErrored && isActive && "border-accent bg-accent/10 text-accent",
                  !isErrored && !isDone && !isActive && "border-border text-text-subtle",
                )}
              >
                {isErrored ? (
                  <XCircle className="h-4 w-4" aria-hidden="true" />
                ) : isDone ? (
                  <Check className="h-4 w-4" aria-hidden="true" />
                ) : isActive ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <span>{index + 1}</span>
                )}
              </div>
              <span
                className={cn(
                  "w-16 text-center text-2xs leading-tight",
                  isErrored
                    ? "text-danger"
                    : isActive || isDone
                      ? "text-text"
                      : "text-text-subtle",
                )}
              >
                {label}
              </span>
            </div>

            {index < STAGE_LABELS.length - 1 && (
              <div
                className={cn(
                  "mx-1 mb-4 h-px flex-1",
                  isConnectorFilled ? "bg-accent/40" : "bg-border",
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
