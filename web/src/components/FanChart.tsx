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
import type { AssetId, Currency } from "../api/types";
import type { FanPoint } from "../lib/chartData";
import { formatDate, formatDayMonth, formatNumber, formatPrice, formatProbability } from "../lib/format";
import { displayUnit } from "../lib/units";

// Token màu theo skill forecast-charts.
const COLOR = { price: "#1F2328", forecast: "#2563EB", muted: "#6B7280", grid: "#E3E6EA" };

interface Props {
  asset: AssetId;
  currency: Currency;
  data: FanPoint[];
  /** Ngày giá cuối (đường dọc "Hôm nay"). */
  baseDate: string;
}

function axisTick(asset: AssetId, currency: Currency) {
  return (value: number) =>
    currency === "VND"
      ? `${formatNumber(value / 1_000_000, 1)} tr`
      : formatNumber(value, asset === "gold" ? 0 : 1);
}

interface TooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: FanPoint }>;
  asset: AssetId;
  currency: Currency;
}

function FanTooltip({ active, payload, asset, currency }: TooltipProps) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  const unit = displayUnit(asset, currency);
  const money = (value: number) => `${formatPrice(asset, value, currency)} ${unit}`;
  const isForecast = point.price === undefined;
  return (
    <div className="tabular rounded-md border border-line bg-white p-3 text-xs shadow-sm">
      <p className="font-medium">{formatDate(point.date)}</p>
      {point.price !== undefined ? <p>Giá: {money(point.price)}</p> : null}
      {isForecast && point.median !== undefined ? (
        <>
          <p>Trung vị: {money(point.median)}</p>
          {point.low !== undefined && point.high !== undefined ? (
            <p>
              Khoảng 80%: {formatPrice(asset, point.low, currency)}–{formatPrice(asset, point.high, currency)}
            </p>
          ) : null}
          {point.probUp !== undefined ? <p>Xác suất tăng: {formatProbability(point.probUp)}</p> : null}
        </>
      ) : null}
    </div>
  );
}

/** Biểu đồ quạt: 90 phiên giá thực + 7 ngày dự báo (dải q10–q90, trung vị nét đứt). */
export function FanChart({ asset, currency, data, baseDate }: Props) {
  const unit = displayUnit(asset, currency);
  return (
    <figure className="rounded-lg border border-line bg-white p-4">
      <figcaption className="mb-2 text-sm font-medium">
        Giá thực tế và dự báo <span className="font-normal text-muted">({unit})</span>
      </figcaption>
      <div
        role="img"
        aria-label={`Biểu đồ giá ${unit} trong 90 phiên gần nhất và dải dự báo 7 ngày, khoảng 80%.`}
        className="h-72 w-full sm:h-96"
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={COLOR.grid} vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={formatDayMonth}
              tick={{ fill: COLOR.muted, fontSize: 12 }}
              minTickGap={32}
              stroke={COLOR.grid}
            />
            <YAxis
              width={56}
              domain={["auto", "auto"]}
              tickFormatter={axisTick(asset, currency)}
              tick={{ fill: COLOR.muted, fontSize: 12 }}
              stroke={COLOR.grid}
            />
            <Tooltip content={<FanTooltip asset={asset} currency={currency} />} />
            <Area
              dataKey={(d: FanPoint) => (d.low != null && d.high != null ? [d.low, d.high] : null)}
              name="Khoảng 80%"
              fill={COLOR.forecast}
              fillOpacity={0.18}
              stroke="none"
              isAnimationActive={false}
              connectNulls
            />
            <Line
              dataKey="price"
              name="Giá thực tế"
              stroke={COLOR.price}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="median"
              name="Trung vị dự báo"
              stroke={COLOR.forecast}
              strokeWidth={2}
              strokeDasharray="6 4"
              dot={false}
              isAnimationActive={false}
            />
            <ReferenceLine
              x={baseDate}
              stroke={COLOR.muted}
              strokeDasharray="2 3"
              label={{ value: "Hôm nay", position: "insideTopRight", fill: COLOR.muted, fontSize: 12 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        <li>
          <span aria-hidden="true" className="mr-1 inline-block h-0.5 w-4 bg-price align-middle" />
          Giá thực tế
        </li>
        <li>
          <span aria-hidden="true" className="mr-1 inline-block w-4 border-t-2 border-dashed border-forecast align-middle" />
          Trung vị dự báo
        </li>
        <li>
          <span aria-hidden="true" className="mr-1 inline-block h-3 w-4 bg-forecast/20 align-middle" />
          Khoảng 80% (q10–q90)
        </li>
      </ul>
    </figure>
  );
}
