import { useNavigate } from "react-router-dom";
import { useEffect, useMemo } from "react";
import { ChevronLeft } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { useForecastStore } from "@/store/forecastStore";
import { useSubmitForecast } from "@/hooks/useForecastJob";
import { cn } from "@/lib/utils";

const REGIONS = [
  { code: "US", label: "United States" },
  { code: "IN", label: "India" },
  { code: "GB", label: "United Kingdom" },
  { code: "DE", label: "Germany" },
  { code: "FR", label: "France" },
  { code: "AU", label: "Australia" },
  { code: "CA", label: "Canada" },
  { code: "JP", label: "Japan" },
];

function MultiSelectChips({
  options,
  selected,
  onToggle,
  emptyHint,
}: {
  options: string[];
  selected: string[];
  onToggle: (val: string) => void;
  emptyHint?: string;
}) {
  if (options.length === 0) {
    return <p className="text-sm text-text-subtle">{emptyHint}</p>;
  }
  return (
    <div className="flex flex-wrap gap-2" role="group">
      {options.map((opt) => {
        const isSelected = selected.includes(opt);
        return (
          <button
            key={opt}
            type="button"
            aria-pressed={isSelected}
            onClick={() => onToggle(opt)}
            className={cn(
              "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
              isSelected
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-border text-text-muted hover:border-border-strong hover:text-text",
            )}
          >
            {opt}
          </button>
        );
      })}
    </div>
  );
}

export function ConfigurePage() {
  const navigate = useNavigate();
  const { upload, config, updateConfig, activeJobId } = useForecastStore();
  const { submit, isSubmitting, error } = useSubmitForecast();

  useEffect(() => {
    if (!upload) navigate("/upload");
  }, [upload, navigate]);

  useEffect(() => {
    if (activeJobId) navigate("/running");
  }, [activeJobId, navigate]);

  const availableColumns = useMemo(() => {
    if (!upload) return [];
    const cols = new Set<string>();
    config.selectedSheets.forEach((sheet) => {
      (upload.columns[sheet] ?? []).forEach((c) => cols.add(c));
    });
    return Array.from(cols).filter((c) => !c.toLowerCase().includes("date"));
  }, [upload, config.selectedSheets]);

  if (!upload) return null;

  const toggleInArray = (
    arr: string[],
    val: string,
    setter: (next: string[]) => void,
  ) => {
    setter(
      arr.includes(val) ? arr.filter((v) => v !== val) : [...arr, val],
    );
  };

  const canSubmit =
    config.selectedSheets.length > 0 && config.selectedMetrics.length > 0;

  const handleSubmit = () => {
    submit({
      upload_id: upload.upload_id,
      selected_sheets: config.selectedSheets,
      selected_metrics: config.selectedMetrics,
      selected_x_cols:
        config.selectedXCols.length > 0 ? config.selectedXCols : undefined,
      forecast_horizon: config.forecastHorizon,
      test_window: config.testWindow,
      selected_regions: config.selectedRegions,
      quantile_level: config.quantileLevel,
    });
  };

  return (
    <div className="mx-auto max-w-3xl">
      <button
        type="button"
        onClick={() => navigate("/upload")}
        className="mb-4 flex items-center gap-1 text-sm text-text-muted hover:text-text"
      >
        <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        Back
      </button>

      <div className="mb-6">
        <h1 className="text-xl font-semibold text-text">
          Configure forecast
        </h1>
        <p className="mt-1 text-sm text-text-muted">
          {upload.file_name} · {upload.sheets.length} sheet
          {upload.sheets.length !== 1 ? "s" : ""}
        </p>
      </div>

      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Sheets to forecast</CardTitle>
          </CardHeader>
          <CardContent>
            <MultiSelectChips
              options={upload.sheets}
              selected={config.selectedSheets}
              onToggle={(s) =>
                toggleInArray(config.selectedSheets, s, (next) =>
                  updateConfig({ selectedSheets: next, selectedMetrics: [] }),
                )
              }
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Metrics to forecast</CardTitle>
          </CardHeader>
          <CardContent>
            <MultiSelectChips
              options={availableColumns}
              selected={config.selectedMetrics}
              onToggle={(m) =>
                toggleInArray(config.selectedMetrics, m, (next) =>
                  updateConfig({ selectedMetrics: next }),
                )
              }
              emptyHint="Select at least one sheet first."
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>External drivers (optional)</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-3 text-xs text-text-subtle">
              Columns to use as predictive features alongside the forecast
              target.
            </p>
            <MultiSelectChips
              options={availableColumns.filter(
                (c) => !config.selectedMetrics.includes(c),
              )}
              selected={config.selectedXCols}
              onToggle={(c) =>
                toggleInArray(config.selectedXCols, c, (next) =>
                  updateConfig({ selectedXCols: next }),
                )
              }
              emptyHint="No additional columns available."
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Forecast settings</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-text-muted">
                Forecast horizon (days)
              </span>
              <input
                type="number"
                min={1}
                max={365}
                value={config.forecastHorizon}
                onChange={(e) =>
                  updateConfig({ forecastHorizon: Number(e.target.value) })
                }
                className="h-9 rounded-md border border-border bg-bg-raised px-3 text-sm font-mono text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-text-muted">
                Test window (days)
              </span>
              <input
                type="number"
                min={7}
                max={180}
                value={config.testWindow}
                onChange={(e) =>
                  updateConfig({ testWindow: Number(e.target.value) })
                }
                className="h-9 rounded-md border border-border bg-bg-raised px-3 text-sm font-mono text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Holiday regions</CardTitle>
          </CardHeader>
          <CardContent>
            <MultiSelectChips
              options={REGIONS.map((r) => r.code)}
              selected={config.selectedRegions}
              onToggle={(r) =>
                toggleInArray(config.selectedRegions, r, (next) =>
                  updateConfig({ selectedRegions: next }),
                )
              }
            />
          </CardContent>
        </Card>

        {error && (
          <div role="alert" className="rounded-md bg-danger/10 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex justify-end pt-2">
          <Button
            onClick={handleSubmit}
            disabled={!canSubmit}
            isLoading={isSubmitting}
            loadingText="Starting forecast…"
            size="lg"
          >
            Run forecast
          </Button>
        </div>
      </div>
    </div>
  );
}