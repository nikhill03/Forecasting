import { Link } from "react-router-dom";
import { Plus, RotateCw, Sparkles, Upload } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { BrandMark } from "@/components/ui/BrandMark";
import { DemandQuadrant } from "@/components/marketing/DemandQuadrant";
import { StatStrip } from "@/components/dashboard/StatStrip";
import { RecentRuns } from "@/components/dashboard/RecentRuns";
import { AccuracySparkline } from "@/components/dashboard/AccuracySparkline";
import { ActiveRuns } from "@/components/dashboard/ActiveRuns";
import { ModelWinsChart } from "@/components/dashboard/ModelWinsChart";
import { RunTimeCard } from "@/components/dashboard/RunTimeCard";
import { useDashboardSummary } from "@/hooks/useDashboardSummary";
import type { DashboardSummary, DemandMix } from "@/types/api";

function EmptyState() {
  return (
    <Card className="tick-corners">
      <CardContent className="flex flex-col items-center gap-4 py-12 text-center">
        <div className="rounded-full bg-accent/10 p-4">
          <BrandMark className="h-8 w-8" />
        </div>
        <div>
          <h2 className="text-base font-semibold text-text">
            Start a new forecast
          </h2>
          <p className="mt-1 max-w-sm text-sm text-text-muted">
            Upload a dataset and we'll automatically classify demand
            patterns and select the best forecasting model.
          </p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Link to="/upload">
            <Button size="lg">
              <Upload className="h-4 w-4" aria-hidden="true" />
              Upload dataset
            </Button>
          </Link>
          {/* Without this, an account with no CSV to hand has nowhere to
              go from the first authenticated screen. */}
          <Link to="/upload">
            <Button variant="secondary" size="lg">
              <Sparkles className="h-4 w-4" aria-hidden="true" />
              Try sample data
            </Button>
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

// Placeholder blocks in the populated layout's shape. Showing the empty state
// while loading would briefly tell a user with runs that they have none.
function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <p role="status" className="sr-only">
        Loading your dashboard…
      </p>
      <div className="h-24 animate-pulse-slow rounded-lg border border-border bg-bg-surface" />
      <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <div className="h-72 animate-pulse-slow rounded-lg border border-border bg-bg-surface" />
        <div className="h-72 animate-pulse-slow rounded-lg border border-border bg-bg-surface" />
      </div>
    </div>
  );
}

function DashboardError({ onRetry }: { onRetry: () => void }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
        <p role="alert" className="text-sm text-text">
          We couldn't load your dashboard.
        </p>
        <Button variant="secondary" onClick={onRetry}>
          <RotateCw className="h-4 w-4" aria-hidden="true" />
          Try again
        </Button>
      </CardContent>
    </Card>
  );
}

function DemandMixCard({ mix }: { mix: DemandMix }) {
  const { unclassified, ...counts } = mix;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Demand mix</CardTitle>
        {unclassified > 0 && (
          <span className="text-xs text-text-subtle">
            +{unclassified} unclassified
          </span>
        )}
      </CardHeader>
      <CardContent>
        {/* The chart scales with its container; uncapped, it grows to ~430px
            tall in the single-column layout and dominates the page. */}
        <div className="mx-auto max-w-md">
          <DemandQuadrant counts={counts} />
        </div>
      </CardContent>
    </Card>
  );
}

// Until something has succeeded there is nothing to chart, and four empty
// cards in a row make a first-time user's dashboard look broken.
function ChartsPending() {
  return (
    <Card>
      <CardContent className="py-8 text-center">
        <p className="text-sm font-medium text-text">
          Your charts will appear here
        </p>
        <p className="mx-auto mt-1 max-w-xs text-xs text-text-muted">
          Accuracy over time, which models win, run time and demand mix fill in
          once a run completes successfully.
        </p>
      </CardContent>
    </Card>
  );
}

function PopulatedDashboard({ summary }: { summary: DashboardSummary }) {
  const hasResults = summary.status_counts.success > 0;

  return (
    <div className="flex flex-col gap-6">
      {/* Renders nothing unless a run is in flight — the most time-sensitive
          thing on the page, so it goes first. */}
      <ActiveRuns runs={summary.active_runs} />

      <Card className="tick-corners">
        <CardContent className="py-5">
          <StatStrip summary={summary} />
        </CardContent>
      </Card>

      {/* items-start: a column must not stretch to the height of the other
          and read as a mostly empty panel. */}
      <div className="grid items-start gap-6 lg:grid-cols-[1.3fr_1fr]">
        <div className="flex flex-col gap-6">
          <RecentRuns runs={summary.recent_runs} />
          {hasResults && <ModelWinsChart wins={summary.model_wins} />}
        </div>
        <div className="flex flex-col gap-6">
          {hasResults ? (
            <>
              <AccuracySparkline points={summary.accuracy_trend} />
              <RunTimeCard
                medianSeconds={summary.median_run_seconds}
                slowest={summary.slowest_runs}
              />
              <DemandMixCard mix={summary.demand_mix} />
            </>
          ) : (
            <ChartsPending />
          )}
        </div>
      </div>
    </div>
  );
}

export function DashboardPage() {
  const { data, isLoading, isError, refetch } = useDashboardSummary();
  const hasRuns = (data?.total_runs ?? 0) > 0;

  let body: JSX.Element;
  if (isLoading) {
    body = <DashboardSkeleton />;
  } else if (isError || !data) {
    body = <DashboardError onRetry={() => void refetch()} />;
  } else if (!hasRuns) {
    body = <EmptyState />;
  } else {
    body = <PopulatedDashboard summary={data} />;
  }

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-text">Dashboard</h1>
          <p className="mt-1 text-sm text-text-muted">
            {hasRuns
              ? "How your forecasting is going."
              : "ML-powered demand forecasting with automatic model selection."}
          </p>
        </div>
        {hasRuns && (
          <Link to="/upload">
            <Button>
              <Plus className="h-4 w-4" aria-hidden="true" />
              New forecast
            </Button>
          </Link>
        )}
      </div>

      {body}
    </div>
  );
}
