import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import type { ForecastRecord } from "@/types/api";
import { formatDate, formatNumber } from "@/lib/format";

interface ForecastChartProps {
  records: ForecastRecord[];
}

interface TooltipPayloadItem {
  color: string;
  name: string;
  value: number;
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-bg-raised px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-medium text-text">{formatDate(label)}</p>
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color }} className="font-mono">
          {p.name}: {formatNumber(p.value)}
        </p>
      ))}
    </div>
  );
}

export function ForecastChart({ records }: ForecastChartProps) {
  const lastActualIndex = records.findIndex(
    (r) => r.TrainActual === null && r.TestActual === null,
  );
  const boundaryDate =
    lastActualIndex > 0 ? records[lastActualIndex - 1]?.Date : undefined;

  return (
    <div className="h-80 w-full" role="img" aria-label="Forecast chart showing historical actuals and future predictions">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={records} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#2A3142"
            vertical={false}
          />
          <XAxis
            dataKey="Date"
            tickFormatter={(d: string) => formatDate(d, { month: "short", day: "numeric" })}
            stroke="#5A6173"
            fontSize={11}
            tickLine={false}
            axisLine={{ stroke: "#2A3142" }}
          />
          <YAxis
            stroke="#5A6173"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => formatNumber(v, 0)}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            wrapperStyle={{ fontSize: 12, color: "#8B92A5" }}
            iconType="line"
          />
          {boundaryDate && (
            <ReferenceLine
              x={boundaryDate}
              stroke="#3B4458"
              strokeDasharray="4 4"
              label={{
                value: "Forecast start",
                position: "insideTopRight",
                fontSize: 10,
                fill: "#8B92A5",
              }}
            />
          )}
          <Line
            type="monotone"
            dataKey="TrainActual"
            name="Actual"
            stroke="#8B92A5"
            strokeWidth={1.5}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="TestActual"
            name="Test Actual"
            stroke="#60A5FA"
            strokeWidth={1.5}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="TestPrediction"
            name="Test Prediction"
            stroke="#FBBF24"
            strokeWidth={1.5}
            strokeDasharray="4 2"
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="Forecast"
            name="Forecast"
            stroke="#5EEAD4"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}