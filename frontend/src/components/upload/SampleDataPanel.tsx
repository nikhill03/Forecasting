import { Play, AlertCircle } from "lucide-react";
import { DemandBadge } from "@/components/ui/DemandBadge";
import { useSamples, useSampleUpload } from "@/hooks/useUpload";
import { DemandTypeSchema } from "@/types/api.schemas";
import type { DemandType, SampleDataset } from "@/types/api";
import { cn } from "@/lib/utils";

// demand_class arrives as a plain string so the catalog can grow past the
// four canonical quadrants without breaking the request. Narrow it here;
// an unrecognised value simply renders without a badge.
function toDemandType(value: string): DemandType | null {
  const parsed = DemandTypeSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

interface SampleCardProps {
  sample: SampleDataset;
  isPending: boolean;
  isDisabled: boolean;
  onSelect: (sampleId: string) => void;
}

function SampleCard({
  sample,
  isPending,
  isDisabled,
  onSelect,
}: SampleCardProps) {
  const demandType = toDemandType(sample.demand_class);

  return (
    <button
      type="button"
      onClick={() => onSelect(sample.id)}
      disabled={isDisabled}
      aria-busy={isPending}
      className={cn(
        "group flex w-full flex-col gap-3 rounded-lg border border-border bg-bg-surface p-4 text-left transition-colors",
        !isDisabled && "hover:border-border-strong hover:bg-bg-raised",
        isDisabled && "cursor-not-allowed opacity-60",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <span className="text-sm font-medium text-text">{sample.title}</span>
        {demandType && <DemandBadge type={demandType} size="sm" />}
      </div>

      <p className="text-xs leading-relaxed text-text-muted">
        {sample.description}
      </p>

      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-2xs text-text-subtle">
          {sample.row_count.toLocaleString()} rows · {sample.frequency}
        </span>
        <span
          className={cn(
            "flex items-center gap-1.5 text-xs font-medium text-accent",
            !isDisabled && "group-hover:text-accent-dim",
          )}
        >
          <Play className="h-3 w-3" aria-hidden="true" />
          {isPending ? "Loading…" : "Use this"}
        </span>
      </div>
    </button>
  );
}

export function SampleDataPanel() {
  const { data: samples, isLoading, isError } = useSamples();
  const { createFromSample, isCreating, pendingId, error } = useSampleUpload();

  if (isLoading) {
    return (
      <p className="text-sm text-text-muted">Loading sample datasets…</p>
    );
  }

  if (isError || !samples || samples.length === 0) {
    // A missing catalog is not worth blocking the page over — the dropzone
    // above still works. Say nothing rather than showing a broken section.
    return null;
  }

  return (
    <section aria-labelledby="sample-data-heading">
      <div className="mb-3">
        <h2
          id="sample-data-heading"
          className="text-sm font-semibold text-text"
        >
          No dataset handy?
        </h2>
        <p className="mt-1 text-xs text-text-muted">
          Start from a built-in sample. Each one lands in a different demand
          quadrant, so you can see how classification changes the models we
          pick.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {samples.map((sample) => (
          <SampleCard
            key={sample.id}
            sample={sample}
            isPending={pendingId === sample.id}
            isDisabled={isCreating}
            onSelect={createFromSample}
          />
        ))}
      </div>

      {error && (
        <div
          role="alert"
          className="mt-3 flex items-center gap-1.5 text-sm text-danger"
        >
          <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          {error}
        </div>
      )}
    </section>
  );
}
