import type { DataQualityReport, QualityIssue } from "@/types/api";

export type Severity = QualityIssue["severity"];

export interface IssueGroup {
  /** "Sheet1 / sales", or null for issues about the selection as a whole. */
  label: string | null;
  issues: QualityIssue[];
}

/** Issues of one severity, grouped under the series they belong to. */
export function groupIssues(
  report: DataQualityReport,
  severity: Severity,
): IssueGroup[] {
  const groups: IssueGroup[] = [];
  const general = report.issues.filter((i) => i.severity === severity);
  if (general.length > 0) groups.push({ label: null, issues: general });
  for (const series of report.series) {
    const issues = series.issues.filter((i) => i.severity === severity);
    if (issues.length > 0) {
      groups.push({ label: `${series.sheet} / ${series.metric}`, issues });
    }
  }
  return groups;
}

export function countIssues(
  report: DataQualityReport,
  severity: Severity,
): number {
  return groupIssues(report, severity).reduce(
    (n, g) => n + g.issues.length,
    0,
  );
}
