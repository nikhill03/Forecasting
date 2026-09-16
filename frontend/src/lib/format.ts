export function formatNumber(
  value: number | null | undefined,
  decimals = 2,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatPercent(
  value: number | null | undefined,
  decimals = 1,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `${value.toFixed(decimals)}%`;
}

// For values stored as a 0–1 fraction (WMAPE, success rate). The null check
// is explicit because `null * 100` is 0 in JavaScript — multiplying before
// calling formatPercent would render a missing value as "0%".
export function formatFractionAsPercent(
  value: number | null | undefined,
  decimals = 1,
): string {
  if (value === null || value === undefined) {
    return "—";
  }
  return formatPercent(value * 100, decimals);
}

// "45s", "3m 57s", "2m", "1h 2m". Seconds are dropped once a duration reaches
// an hour — at that scale they're noise.
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) {
    return "—";
  }
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;

  if (hours > 0) return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  if (minutes > 0) return secs > 0 ? `${minutes}m ${secs}s` : `${minutes}m`;
  return `${secs}s`;
}

export function formatWmape(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return value.toFixed(4);
}

export function formatDate(
  dateStr: string | null | undefined,
  options: Intl.DateTimeFormatOptions = {
    year: "numeric",
    month: "short",
    day: "numeric",
  },
): string {
  if (!dateStr) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, options).format(
      new Date(dateStr),
    );
  } catch {
    return dateStr;
  }
}

export function formatRelativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const date = new Date(dateStr);
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);

  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}