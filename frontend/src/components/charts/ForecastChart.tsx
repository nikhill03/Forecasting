import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";
import type { ForecastRecord } from "@/types/api";
import { formatDate, formatNumber } from "@/lib/format";

interface ForecastChartProps {
  records: ForecastRecord[];
}

// Colors carried over as-is from the previous Recharts implementation —
// this swap is about adding zoom/pan, not a visual redesign (full site
// re-theme is planned separately).
const COLOR_AXIS_LINE  = "#2A3142";
const COLOR_AXIS_TEXT  = "#5A6173";
const COLOR_LEGEND     = "#8B92A5";
const COLOR_TOOLTIP_BG = "#1C212E";
const COLOR_TEXT       = "#E8EAED";
const COLOR_BOUNDARY   = "#3B4458";

const COLOR_ACTUAL          = "#8B92A5";
const COLOR_TEST_ACTUAL     = "#60A5FA";
const COLOR_TEST_PREDICTION = "#FBBF24";
const COLOR_FORECAST        = "#5EEAD4";

export function ForecastChart({ records }: ForecastChartProps) {
  const lastActualIndex = records.findIndex(
    (r) => r.TrainActual === null && r.TestActual === null,
  );
  const boundaryDate =
    lastActualIndex > 0 ? records[lastActualIndex - 1]?.Date : undefined;

  const dates = records.map((r) => r.Date);

  const option: EChartsOption = {
    grid: { left: 8, right: 16, top: 24, bottom: 64, containLabel: true },
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
        const date = dates[first.dataIndex];
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
          date,
        )}</div>${rows}`;
      },
    },
    legend: {
      bottom: 0,
      textStyle: { color: COLOR_LEGEND, fontSize: 12 },
      icon: "line",
    },
    dataZoom: [
      { type: "inside", xAxisIndex: 0 },
      {
        type: "slider",
        xAxisIndex: 0,
        height: 18,
        bottom: 28,
        borderColor: COLOR_AXIS_LINE,
        backgroundColor: "transparent",
        fillerColor: "rgba(94, 234, 212, 0.12)",
        handleStyle: { color: COLOR_BOUNDARY },
        textStyle: { color: COLOR_AXIS_TEXT, fontSize: 10 },
        dataBackground: {
          lineStyle: { color: COLOR_AXIS_LINE },
          areaStyle: { color: COLOR_AXIS_LINE },
        },
      },
    ],
    series: [
      {
        name: "Actual",
        type: "line",
        data: records.map((r) => r.TrainActual),
        connectNulls: true,
        showSymbol: false,
        lineStyle: { color: COLOR_ACTUAL, width: 1.5 },
        itemStyle: { color: COLOR_ACTUAL },
        markLine: boundaryDate
          ? {
              silent: true,
              symbol: "none",
              lineStyle: { color: COLOR_BOUNDARY, type: "dashed" },
              label: {
                formatter: "Forecast start",
                color: COLOR_LEGEND,
                fontSize: 10,
                position: "insideEndTop",
              },
              data: [{ xAxis: boundaryDate }],
            }
          : undefined,
      },
      {
        name: "Test Actual",
        type: "line",
        data: records.map((r) => r.TestActual),
        connectNulls: true,
        showSymbol: false,
        lineStyle: { color: COLOR_TEST_ACTUAL, width: 1.5 },
        itemStyle: { color: COLOR_TEST_ACTUAL },
      },
      {
        name: "Test Prediction",
        type: "line",
        data: records.map((r) => r.TestPrediction),
        connectNulls: true,
        showSymbol: false,
        lineStyle: { color: COLOR_TEST_PREDICTION, width: 1.5, type: "dashed" },
        itemStyle: { color: COLOR_TEST_PREDICTION },
      },
      {
        name: "Forecast",
        type: "line",
        data: records.map((r) => r.Forecast),
        connectNulls: true,
        showSymbol: false,
        lineStyle: { color: COLOR_FORECAST, width: 2 },
        itemStyle: { color: COLOR_FORECAST },
      },
    ],
  };

  return (
    <div
      className="h-80 w-full"
      role="img"
      aria-label="Forecast chart showing historical actuals and future predictions — scroll or drag to zoom"
    >
      <ReactECharts
        option={option}
        style={{ height: "100%", width: "100%" }}
        opts={{ renderer: "svg" }}
      />
    </div>
  );
}
