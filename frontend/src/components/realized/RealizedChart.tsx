import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";
import type { RealizedPoint } from "@/types/api";
import { formatDate, formatNumber } from "@/lib/format";
import {
  COLOR_ADJUSTED,
  COLOR_AXIS_LINE,
  COLOR_AXIS_TEXT,
  COLOR_FORECAST,
  COLOR_LEGEND,
  COLOR_TEST_ACTUAL,
  COLOR_TEXT,
  COLOR_TOOLTIP_BG,
} from "@/components/charts/chartColors";

interface RealizedChartProps {
  points: RealizedPoint[];
}

// What happened vs what was forecast, on the dates both exist. Colours follow
// ForecastChart: blue is the observed series, amber the model's forecast. The
// adjusted line is also dashed, so it never relies on hue alone.
export function RealizedChart({ points }: RealizedChartProps) {
  const dates = points.map((p) => p.date);
  const hasAdjusted = points.some((p) => p.adjusted_forecast !== null);

  const option: EChartsOption = {
    grid: { left: 8, right: 16, top: 16, bottom: 36, containLabel: true },
    xAxis: {
      type: "category",
      data: dates,
      axisLine: { lineStyle: { color: COLOR_AXIS_LINE } },
      axisTick: { show: false },
      axisLabel: {
        color: COLOR_AXIS_TEXT,
        fontSize: 11,
        formatter: (value: string) =>
          formatDate(value, { month: "short", day: "numeric" }),
      },
    },
    yAxis: {
      type: "value",
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: COLOR_AXIS_LINE, type: "dashed" } },
      axisLabel: {
        color: COLOR_AXIS_TEXT,
        fontSize: 11,
        formatter: (value: number) => formatNumber(value, 0),
      },
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: COLOR_TOOLTIP_BG,
      borderColor: COLOR_AXIS_LINE,
      borderWidth: 1,
      textStyle: { color: COLOR_TEXT, fontSize: 12 },
      formatter: (params) => {
        const items = Array.isArray(params) ? params : [params];
        const first = items[0];
        if (!first || first.dataIndex === undefined) return "";
        const rows = items
          .filter((p) => p.value !== null && p.value !== undefined)
          .map(
            (p) =>
              `<div style="color:${String(p.color)}">${p.seriesName}: ${formatNumber(
                Number(p.value),
              )}</div>`,
          )
          .join("");
        return `<div style="font-weight:600;margin-bottom:4px">${formatDate(
          dates[first.dataIndex],
        )}</div>${rows}`;
      },
    },
    legend: {
      bottom: 0,
      textStyle: { color: COLOR_LEGEND, fontSize: 12 },
      icon: "line",
    },
    series: [
      {
        name: "Actual",
        type: "line",
        data: points.map((p) => p.actual),
        showSymbol: points.length <= 31,
        symbolSize: 5,
        lineStyle: { color: COLOR_TEST_ACTUAL, width: 1.5 },
        itemStyle: { color: COLOR_TEST_ACTUAL },
      },
      {
        name: "Forecast",
        type: "line",
        data: points.map((p) => p.forecast),
        showSymbol: false,
        lineStyle: { color: COLOR_FORECAST, width: 2 },
        itemStyle: { color: COLOR_FORECAST },
      },
      ...(hasAdjusted
        ? [
            {
              name: "Your adjusted forecast",
              type: "line" as const,
              data: points.map((p) => p.adjusted_forecast),
              showSymbol: false,
              lineStyle: { color: COLOR_ADJUSTED, width: 2, type: "dashed" as const },
              itemStyle: { color: COLOR_ADJUSTED },
            },
          ]
        : []),
    ],
  };

  return (
    <div className="flex flex-col gap-2">
      <div
        className="h-64 w-full"
        role="img"
        aria-label="Actual values compared with the forecast on the dates that have actuals"
      >
        <ReactECharts
          option={option}
          style={{ height: "100%", width: "100%" }}
          opts={{ renderer: "svg" }}
        />
      </div>

      <details className="text-xs text-text-muted">
        <summary className="cursor-pointer select-none hover:text-text">
          Show values
        </summary>
        <div className="mt-2 max-h-56 overflow-auto">
          <table className="w-full border-collapse">
            <caption className="sr-only">
              Actual and forecast values on each measured date
            </caption>
            <thead>
              <tr className="border-b border-border text-left text-text-subtle">
                <th scope="col" className="py-1.5 pr-3 font-medium">Date</th>
                <th scope="col" className="py-1.5 pr-3 text-right font-medium">Actual</th>
                <th scope="col" className="py-1.5 pr-3 text-right font-medium">Forecast</th>
                {hasAdjusted && (
                  <th scope="col" className="py-1.5 text-right font-medium">Adjusted</th>
                )}
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.date} className="border-b border-border/50 last:border-0">
                  <td className="py-1.5 pr-3">{formatDate(p.date)}</td>
                  <td className="py-1.5 pr-3 text-right font-mono tabular-nums">
                    {formatNumber(p.actual)}
                  </td>
                  <td className="py-1.5 pr-3 text-right font-mono tabular-nums">
                    {formatNumber(p.forecast)}
                  </td>
                  {hasAdjusted && (
                    <td className="py-1.5 text-right font-mono tabular-nums">
                      {formatNumber(p.adjusted_forecast)}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
