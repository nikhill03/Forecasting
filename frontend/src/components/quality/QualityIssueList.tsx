import { OctagonX, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import type { QualityIssue } from "@/types/api";
import type { IssueGroup } from "@/lib/qualityIssues";

interface QualityIssueListProps {
  groups: IssueGroup[];
  severity: QualityIssue["severity"];
}

export function QualityIssueList({ groups, severity }: QualityIssueListProps) {
  const Icon = severity === "blocking" ? OctagonX : TriangleAlert;

  return (
    <div className="flex flex-col gap-3">
      {groups.map((group) => (
        <div key={group.label ?? "__selection"}>
          {group.label && (
            <p className="mb-1 font-mono text-xs text-text-muted">
              {group.label}
            </p>
          )}
          <ul className="flex flex-col gap-1.5">
            {group.issues.map((issue, index) => (
              <li
                key={`${issue.code}-${index}`}
                className="flex items-start gap-2 text-sm text-text"
              >
                <Icon
                  className={cn(
                    "mt-0.5 h-4 w-4 shrink-0",
                    severity === "blocking" ? "text-danger" : "text-warning",
                  )}
                  aria-hidden="true"
                />
                <span>{issue.message}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
