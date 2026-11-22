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
import { CHART } from "../lib/chartTheme";
import type { ReturnFanPoint } from "../lib/chartData";
import { formatDate, formatNumber, formatReturnPercent } from "../lib/format";
import { GUIDE_ANCHORS, HowToRead } from "./HowToRead";
import { useEntrance } from "../lib/motion";

/** Tiêu đề khối (test và trang hướng dẫn dùng lại). */
export const RETURN_FAN_TITLE = "Mức thay đổi dự báo theo số phiên tới";

interface TooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: ReturnFanPoint }>;
}

function ReturnTooltip({ active, payload }: TooltipProps) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  const pct = (value: number) => formatReturnPercent(value / 100);
  return (
    <div className="tabular rounded-md border border-line bg-surface p-3 text-xs text-price shadow-sm">
      <p className="font-medium">
        {point.h === 0 ? "Phiên gần nhất" : `Sau ${point.h} phiên`} (phiên {formatDate(point.date)})
      </p>
      <p>Mức giữa (trung vị): {pct(point.median)}</p>
      <p>
        Khoảng 80%: {pct(point.q10)} đến {pct(point.q90)}
      </p>
      <p>
        Khoảng 90%: {pct(point.q05)} đến {pct(point.q95)}
      </p>
    </div>
  );
}

/** Quạt theo log return (%) cho h = 0…7, dải 80% đậm hơn dải 90%. */
export function ReturnFanChart({ data }: { data: ReturnFanPoint[] }) {
  // Lần đầu: hai dải hiện dần rồi đường trung vị (CSS .chart-enter); sau đó tức thì
  const entering = useEntrance(900);
  return (
    <section aria-labelledby="return-fan-title" className="rounded-lg border border-line bg-surface p-4 sm:p-5">
      <h2 id="return-fan-title" className="text-lg font-semibold">
        {RETURN_FAN_TITLE} <span className="text-sm font-normal text-muted">(log return, %)</span>
      </h2>
      <HowToRead anchor={GUIDE_ANCHORS.logReturn} topic="log return và quạt dự báo">
        trục ngang là số phiên giao dịch tính từ phiên gần nhất, trục dọc là mức thay đổi so với giá cuối phiên
        đó. Quạt rộng dần sang phải vì càng nhiều phiên, giá càng khó đoán; đường 0% là giá không đổi.
      </HowToRead>

      <div
        role="img"
        aria-label="Biểu đồ mức thay đổi dự báo (log return) theo số phiên tới, có dải khoảng 80% và 90%. Bảng theo từng phiên có đủ số liệu."
        className={`mt-3 h-64 w-full sm:h-80 ${entering ? "chart-enter" : ""}`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 16, left: 0 }}>
            <CartesianGrid stroke={CHART.grid} vertical={false} />
            <XAxis
              dataKey="h"
              tickFormatter={(h: number) => String(h)}
              tick={{ fill: CHART.muted, fontSize: 12 }}
              stroke={CHART.grid}
              tickLine={false}
              label={{
                value: "Số phiên tới (h)",
                position: "insideBottom",
                offset: -12,
                fill: CHART.muted,
                fontSize: 12,
              }}
            />
            <YAxis
              width={56}
              domain={["auto", "auto"]}
              tickFormatter={(v: number) => `${formatNumber(v, 1)}%`}
              tick={{ fill: CHART.muted, fontSize: 12 }}
              stroke={CHART.grid}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip content={<ReturnTooltip />} cursor={{ stroke: CHART.muted, strokeDasharray: "2 3" }} />
            <Area
              dataKey={(d: ReturnFanPoint) => [d.q05, d.q95]}
              name="Khoảng 90%"
              fill={CHART.band}
              fillOpacity={0.45}
              stroke="none"
              activeDot={false}
              isAnimationActive={false}
            />
            <Area
              dataKey={(d: ReturnFanPoint) => [d.q10, d.q90]}
              name="Khoảng 80%"
              fill={CHART.band}
              fillOpacity={1}
              stroke="none"
              activeDot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="median"
              name="Trung vị"
              stroke={CHART.forecast}
              strokeWidth={2}
              strokeDasharray="6 4"
              className="chart-median-line"
              dot={false}
              activeDot={{ r: 4, fill: CHART.forecast, stroke: CHART.surface, strokeWidth: 2 }}
              isAnimationActive={false}
            />
            <ReferenceLine y={0} stroke={CHART.muted} strokeDasharray="2 3" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <ul aria-label="Chú thích biểu đồ" className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted">
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block w-4 border-t-2 border-dashed border-forecast" />
          Mức giữa (trung vị, q50)
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-3 w-4 rounded-sm bg-band" />
          Khoảng 80% (q10–q90)
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-3 w-4 rounded-sm bg-band/45" />
          Khoảng 90% (q05–q95)
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block w-4 border-t border-dotted border-muted" />
          0%: giá không đổi
        </li>
      </ul>
    </section>
  );
}
