import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ReturnFanPoint } from "../lib/chartData";
import { formatDate, formatNumber, formatReturnPercent } from "../lib/format";

const COLOR = { forecast: "#2563EB", muted: "#6B7280", grid: "#E3E6EA" };

interface TooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: ReturnFanPoint }>;
}

function ReturnTooltip({ active, payload }: TooltipProps) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  const pct = (value: number) => formatReturnPercent(value / 100);
  return (
    <div className="tabular rounded-md border border-line bg-white p-3 text-xs shadow-sm">
      <p className="font-medium">
        h = {point.h} · {formatDate(point.date)}
      </p>
      <p>Trung vị: {pct(point.median)}</p>
      <p>
        Khoảng 80%: {pct(point.q10)} đến {pct(point.q90)}
      </p>
      <p>
        Khoảng 90%: {pct(point.q05)} đến {pct(point.q95)}
      </p>
    </div>
  );
}

/** Chế độ nâng cao: quạt theo log return (%) cho h = 0…7, dải 80% đậm hơn dải 90%. */
export function ReturnFanChart({ data }: { data: ReturnFanPoint[] }) {
  return (
    <figure className="rounded-lg border border-line bg-white p-4">
      <figcaption className="mb-2 text-sm font-medium">
        Quạt log return theo số phiên h <span className="font-normal text-muted">(%)</span>
      </figcaption>
      <div
        role="img"
        aria-label="Biểu đồ log return dự báo theo số phiên h, dải khoảng 80% và 90%. Bảng bên dưới có đủ số liệu."
        className="h-64 w-full sm:h-80"
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={COLOR.grid} vertical={false} />
            <XAxis
              dataKey="h"
              tickFormatter={(h: number) => `h=${h}`}
              tick={{ fill: COLOR.muted, fontSize: 12 }}
              stroke={COLOR.grid}
            />
            <YAxis
              width={56}
              domain={["auto", "auto"]}
              tickFormatter={(v: number) => `${formatNumber(v, 1)}%`}
              tick={{ fill: COLOR.muted, fontSize: 12 }}
              stroke={COLOR.grid}
            />
            <Tooltip content={<ReturnTooltip />} />
            <Area
              dataKey={(d: ReturnFanPoint) => [d.q05, d.q95]}
              name="Khoảng 90%"
              fill={COLOR.forecast}
              fillOpacity={0.1}
              stroke="none"
              isAnimationActive={false}
            />
            <Area
              dataKey={(d: ReturnFanPoint) => [d.q10, d.q90]}
              name="Khoảng 80%"
              fill={COLOR.forecast}
              fillOpacity={0.18}
              stroke="none"
              isAnimationActive={false}
            />
            <Line
              dataKey="median"
              name="Trung vị"
              stroke={COLOR.forecast}
              strokeWidth={2}
              strokeDasharray="6 4"
              dot={false}
              isAnimationActive={false}
            />
            <ReferenceLine y={0} stroke={COLOR.muted} strokeDasharray="2 3" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
