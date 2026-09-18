import { useId, useState } from "react";
import { ChevronDown, CircleCheck, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import type { DataQualityReport } from "@/types/api";
import { countIssues, groupIssues } from "@/lib/qualityIssues";
import { QualityIssueList } from "./QualityIssueList";

interface DataQualityCaveatsProps {
  /** null for runs created before the data check existed. */
  report: DataQualityReport | null;
}

/**
 * The data warnings a finished run was built on. A job can never carry a
 * blocking issue — POST /forecast refuses those — so only warnings appear.
 */
export function DataQualityCaveats({ report }: DataQualityCaveatsProps) {
  const [isOpen, setIsOpen] = useState(false);
  const panelId = useId();

  if (report === null) {
    return (
      <p className="text-xs text-text-subtle">
        No data check for this run — it was created before data checks were
        added.
      </p>
    );
  }

  const count = countIssues(report, "warning");
  if (count === 0) {
    return (
      <p className="flex items-center gap-2 text-xs text-text-muted">
        <CircleCheck className="h-3.5 w-3.5 text-success" aria-hidden="true" />
        No data warnings for this run.
      </p>
    );
  }

  return (
    <div className="rounded-md border border-border bg-bg-surface">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        aria-expanded={isOpen}
        aria-controls={panelId}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm text-text hover:bg-bg-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <TriangleAlert className="h-4 w-4 text-warning" aria-hidden="true" />
        Built on data with {count} {count === 1 ? "warning" : "warnings"}
        <ChevronDown
          className={cn(
            "ml-auto h-4 w-4 text-text-muted transition-transform motion-reduce:transition-none",
            isOpen && "rotate-180",
          )}
          aria-hidden="true"
        />
      </button>
      {isOpen && (
        <div id={panelId} className="border-t border-border px-4 py-3">
          <QualityIssueList
            groups={groupIssues(report, "warning")}
            severity="warning"
          />
        </div>
      )}
    </div>
  );
}
