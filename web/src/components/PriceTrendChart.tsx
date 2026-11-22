import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AssetId, Currency } from "../api/types";
import { ASSET_COLOR, CHART } from "../lib/chartTheme";
import {
  MONTH_TICKS_FROM_POINTS,
  dateTickFormatter,
  formatAxisPrice,
  formatDate,
  formatPrice,
  monthStartTicks,
} from "../lib/format";
import { displayUnit } from "../lib/units";

export interface TrendPoint {
  date: string;
  /** Giá đã quy đổi theo đơn vị tiền đang chọn. */
  price: number;
}

interface Props {
  asset: AssetId;
  currency: Currency;
  data: TrendPoint[];
  /** Mô tả cho trình đọc màn hình, ví dụ "Giá cuối phiên dầu WTI trong 1 tháng". */
  label: string;
}

interface TooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: TrendPoint }>;
  asset: AssetId;
  currency: Currency;
}

function TrendTooltip({ active, payload, asset, currency }: TooltipProps) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="tabular rounded-md border border-line bg-surface px-3 py-2 text-xs text-price shadow-sm">
      <p className="text-muted">{formatDate(point.date)}</p>
      <p className="mt-0.5 font-medium">
        {formatPrice(asset, point.price, currency)} {displayUnit(asset, currency)}
      </p>
    </div>
  );
}

/**
 * Đường giá cuối phiên (không có dữ liệu trong ngày), màu nhận diện của sản phẩm để khớp với ô đang
 * chọn. Trục tung không bắt đầu từ 0, có ghi chú ở khối chứa.
 */
export function PriceTrendChart({ asset, currency, data, label }: Props) {
  const last = data[data.length - 1];
  const color = ASSET_COLOR[asset];
  const ticks = data.length > MONTH_TICKS_FROM_POINTS ? monthStartTicks(data.map((point) => point.date)) : undefined;
  return (
    <div role="img" aria-label={label} className="h-64 w-full sm:h-80">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 12, right: 12, bottom: 0, left: 0 }} accessibilityLayer={false}>
          <CartesianGrid stroke={CHART.grid} vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={dateTickFormatter(data.length)}
            ticks={ticks}
            tick={{ fill: CHART.muted, fontSize: 12 }}
            minTickGap={28}
            stroke={CHART.grid}
            tickLine={false}
          />
          <YAxis
            width={60}
            domain={["auto", "auto"]}
            tickFormatter={formatAxisPrice(asset, currency)}
            tick={{ fill: CHART.muted, fontSize: 12 }}
            stroke={CHART.grid}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            content={<TrendTooltip asset={asset} currency={currency} />}
            cursor={{ stroke: CHART.muted, strokeDasharray: "2 3" }}
          />
          <Line
            dataKey="price"
            name="Giá cuối phiên"
            stroke={color}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: color, stroke: CHART.surface, strokeWidth: 2 }}
            isAnimationActive={false}
          />
          {last ? (
            <ReferenceDot
              x={last.date}
              y={last.price}
              r={4}
              fill={color}
              stroke={CHART.surface}
              strokeWidth={2}
              ifOverflow="visible"
            />
          ) : null}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
