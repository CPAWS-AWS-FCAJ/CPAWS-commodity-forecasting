import { useMemo, useState } from "react";
import {
  Area,
  Brush,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AssetId, ClosePoint, Currency, ForecastDetail } from "../api/types";
import { CHART } from "../lib/chartTheme";
import { buildFanData, describeMedianChange } from "../lib/chartData";
import type { FanPoint } from "../lib/chartData";
import {
  MONTH_TICKS_FROM_POINTS,
  dateTickFormatter,
  formatAxisPrice,
  formatDate,
  formatPrice,
  monthStartTicks,
} from "../lib/format";
import { describeProbability } from "../lib/forecast";
import {
  DIRECTION_ARROW,
  DIRECTION_CLASS,
  DIRECTION_WORD,
  FORECAST_CHART_RANGES,
  defaultRange,
  isRangeAvailable,
  sliceRange,
} from "../lib/priceOverview";
import type { HistoryRange } from "../lib/priceOverview";
import { displayUnit } from "../lib/units";
import { GUIDE_ANCHORS, HowToRead } from "./HowToRead";
import { RangePicker } from "./RangePicker";

interface Props {
  asset: AssetId;
  currency: Currency;
  detail: ForecastDetail;
  /** `price_history` của API (cũ → mới); undefined khi chưa tải được lịch sử. */
  history: readonly ClosePoint[] | undefined;
  /** Gọi lịch sử lỗi: biểu đồ vẫn vẽ phần dự báo. */
  historyFailed?: boolean;
}

/**
 * Mặc định xem 1 tháng (giống trang Tổng quan giá) để 7 phiên dự báo và chấm trung vị đủ rộng;
 * người dùng tự chọn 6 tháng–2 năm khi muốn xem dòng chảy dài.
 */
const DEFAULT_MAX_SESSIONS = 21;
/** Khung nhỏ nhất khi phóng to bằng nút: 7 phiên dự báo + phiên gần nhất + 7 phiên lịch sử. */
const MIN_WINDOW = 15;
/** Ít điểm hơn thì không cần thanh chọn đoạn. */
const BRUSH_FROM_POINTS = MIN_WINDOW + 1;

interface Window {
  start: number;
  end: number;
}

interface TooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: FanPoint }>;
  asset: AssetId;
  currency: Currency;
  baseDate: string;
}

function FanTooltip({ active, payload, asset, currency, baseDate }: TooltipProps) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  const unit = displayUnit(asset, currency);
  const money = (value: number) => `${formatPrice(asset, value, currency)} ${unit}`;

  if (point.h === undefined) {
    return (
      <div className="tabular rounded-md border border-line bg-surface p-3 text-xs text-price shadow-sm">
        <p className="font-medium">{formatDate(point.date)}</p>
        {point.price !== undefined ? (
          <p>
            {point.date === baseDate ? "Giá cuối phiên gần nhất" : "Giá cuối phiên"}: {money(point.price)}
          </p>
        ) : null}
      </div>
    );
  }

  const change = point.changeMid !== undefined ? describeMedianChange(point.changeMid) : null;
  return (
    <div className="tabular max-w-72 rounded-md border border-line bg-surface p-3 text-xs text-price shadow-sm">
      <p className="font-medium">
        Sau {point.h} phiên (phiên {formatDate(point.date)})
      </p>
      {point.median !== undefined ? (
        <p className="mt-1 flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block size-2.5 shrink-0 rounded-full bg-median-dot" />
          <span>
            Trung vị dự báo (chấm đỏ): <strong>{money(point.median)}</strong>
          </span>
        </p>
      ) : null}
      {change ? (
        <p className="mt-0.5">
          So với giá cuối {formatDate(baseDate)}:{" "}
          <span className={DIRECTION_CLASS[change.direction]}>
            <span aria-hidden="true">{DIRECTION_ARROW[change.direction]} </span>
            {DIRECTION_WORD[change.direction]} {change.magnitude}
          </span>
        </p>
      ) : null}
      {point.low !== undefined && point.high !== undefined ? (
        <p className="mt-0.5">
          Khoảng 80%: {formatPrice(asset, point.low, currency)}–{formatPrice(asset, point.high, currency)} {unit}
        </p>
      ) : null}
      {point.probUp !== undefined ? (
        <p className="mt-0.5">Xác suất tăng: {describeProbability(point.probUp).probUpLabel}</p>
      ) : null}
      <p className="mt-1.5 text-muted">Chấm đỏ đánh dấu mức giữa của dự báo, không có nghĩa là giảm.</p>
    </div>
  );
}

interface DotProps {
  cx?: number;
  cy?: number;
  index?: number;
  payload?: FanPoint;
}

/** Chấm trung vị cho từng phiên h = 1…7; điểm nối và điểm lịch sử không có chấm. */
function medianDot(radius: number) {
  return function MedianDot({ cx, cy, index, payload }: DotProps) {
    const key = `median-dot-${radius}-${index ?? 0}`;
    if (cx == null || cy == null || payload?.h === undefined) return <g key={key} />;
    return (
      <circle
        key={key}
        cx={cx}
        cy={cy}
        r={radius}
        fill={CHART.medianDot}
        stroke={CHART.surface}
        strokeWidth={1.5}
      />
    );
  };
}

// Khung càng nhiều phiên thì 7 chấm càng sát nhau: thu nhỏ chấm để không chồng lên nhau.
const MEDIAN_DOTS = { large: medianDot(4), medium: medianDot(3), small: medianDot(2.5) };
const MEDIAN_DOT_ACTIVE = medianDot(6);

function medianDotFor(visiblePoints: number) {
  if (visiblePoints > 100) return MEDIAN_DOTS.small;
  if (visiblePoints > 50) return MEDIAN_DOTS.medium;
  return MEDIAN_DOTS.large;
}

/**
 * "Giá thực tế và dự báo": giá cuối phiên theo mốc 1 tháng / 6 tháng / 1 năm / 2 năm + 7 phiên dự báo
 * (dải q10–q90, trung vị nét đứt, chấm đỏ trung vị từng phiên). Phóng to bằng thanh Brush, nút
 * Phóng to / Thu nhỏ (giữ mép phải) và Đặt lại (về cả mốc, luôn thấy phần dự báo).
 */
export function FanChart({ asset, currency, detail, history, historyFailed = false }: Props) {
  const unit = displayUnit(asset, currency);
  const closes = history ?? [];
  const pointCount = closes.length;

  // undefined = theo mặc định; mốc đã chọn mà không còn đủ dữ liệu thì cũng về mặc định
  const [chosen, setChosen] = useState<HistoryRange["id"] | undefined>(undefined);
  const chosenRange = FORECAST_CHART_RANGES.find((range) => range.id === chosen);
  const range =
    chosenRange && isRangeAvailable(chosenRange, pointCount)
      ? chosenRange
      : defaultRange(FORECAST_CHART_RANGES, pointCount, DEFAULT_MAX_SESSIONS);

  const data = useMemo(
    () => buildFanData(asset, detail, sliceRange(closes, range), currency),
    [asset, detail, closes, range, currency],
  );
  const last = data.length - 1;

  // Khung đang xem (chỉ số trong `data`); null = cả mốc. `brushToken` đổi khi khung đổi bằng nút để
  // Brush dựng lại đúng vị trí (Brush tự giữ trạng thái khi đang kéo).
  const [win, setWin] = useState<Window | null>(null);
  const [brushToken, setBrushToken] = useState(0);
  const start = win ? Math.min(Math.max(win.start, 0), last) : 0;
  const end = win ? Math.min(Math.max(win.end, start), last) : last;
  const visible = end - start + 1;
  const zoomed = start > 0 || end < last;
  const forecastCut = end < last;
  const showBrush = data.length >= BRUSH_FROM_POINTS;

  const setWindowFromButton = (next: Window | null) => {
    setWin(next);
    setBrushToken((token) => token + 1);
  };
  const zoomIn = () => {
    const size = Math.max(MIN_WINDOW, Math.ceil(visible / 2));
    setWindowFromButton({ start: Math.max(0, end - size + 1), end });
  };
  const zoomOut = () => {
    const size = Math.min(data.length, visible * 2);
    const nextStart = end - size + 1;
    if (nextStart <= 0 && size >= data.length) setWindowFromButton(null);
    else if (nextStart < 0) setWindowFromButton({ start: 0, end: Math.min(last, size - 1) });
    else setWindowFromButton({ start: nextStart, end });
  };
  const onRangeChange = (next: HistoryRange) => {
    setChosen(next.id);
    setWindowFromButton(null);
  };

  const finalPoint = data[last];
  const firstDate = data[0]?.date;
  const desc =
    finalPoint?.median !== undefined && finalPoint.low !== undefined && finalPoint.high !== undefined
      ? `Giá cuối phiên từ ${formatDate(firstDate)} đến ${formatDate(detail.base_date)}. Trung vị dự báo phiên ${formatDate(
          finalPoint.date,
        )} là ${formatPrice(asset, finalPoint.median, currency)} ${unit}, khoảng 80% từ ${formatPrice(
          asset,
          finalPoint.low,
          currency,
        )} đến ${formatPrice(asset, finalPoint.high, currency)} ${unit}.`
      : "";
  const tickFormatter = dateTickFormatter(visible);
  const monthTicks = useMemo(
    () =>
      visible > MONTH_TICKS_FROM_POINTS ? monthStartTicks(data.slice(start, end + 1).map((point) => point.date)) : undefined,
    [data, start, end, visible],
  );

  return (
    <section aria-labelledby="fan-chart-title" className="rounded-lg border border-line bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="fan-chart-title" className="text-lg font-semibold">
            Giá thực tế và dự báo <span className="text-sm font-normal text-muted">({unit})</span>
          </h2>
          <HowToRead anchor={GUIDE_ANCHORS.chart} topic="biểu đồ giá và dự báo">
            đường liền là giá cuối phiên đã có; bên phải phiên gần nhất là 7 phiên dự báo, với dải xanh là khoảng
            80% và chấm đỏ là mức giữa (trung vị) của từng phiên.
          </HowToRead>
        </div>
        {pointCount > 0 ? (
          <RangePicker
            label="Mốc xem lịch sử giá"
            ranges={FORECAST_CHART_RANGES}
            value={range?.id ?? null}
            pointCount={pointCount}
            onChange={onRangeChange}
          />
        ) : null}
      </div>

      {historyFailed ? (
        <p role="status" className="mt-3 text-sm text-warn-fg">
          Chưa tải được lịch sử giá; biểu đồ chỉ vẽ phần dự báo.
        </p>
      ) : null}
      {!historyFailed && pointCount > 0 && range === null ? (
        <p className="mt-3 text-sm text-muted">Đang hiện toàn bộ {pointCount} phiên giá cuối hiện có.</p>
      ) : null}

      <p className="mt-3 text-xs text-muted">Trục dọc: {unit}, không bắt đầu từ 0.</p>
      <div
        className={`mt-1 h-80 w-full sm:h-[26rem] [&_.recharts-brush-traveller:focus-visible_rect]:fill-forecast`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={data}
            margin={{ top: 8, right: 16, bottom: 0, left: 0 }}
            title={`Giá thực tế và dự báo, ${unit}`}
            desc={desc}
          >
            <CartesianGrid stroke={CHART.grid} vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={tickFormatter}
              ticks={monthTicks}
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
              content={<FanTooltip asset={asset} currency={currency} baseDate={detail.base_date} />}
              cursor={{ stroke: CHART.muted, strokeDasharray: "2 3" }}
            />
            <Area
              dataKey={(d: FanPoint) => (d.low != null && d.high != null ? [d.low, d.high] : null)}
              name="Khoảng 80%"
              fill={CHART.band}
              fillOpacity={0.9}
              stroke="none"
              activeDot={false}
              isAnimationActive={false}
              connectNulls
            />
            <Line
              dataKey="price"
              name="Giá thực tế"
              stroke={CHART.price}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: CHART.price, stroke: CHART.surface, strokeWidth: 2 }}
              isAnimationActive={false}
            />
            <Line
              dataKey="median"
              name="Trung vị dự báo từng phiên"
              stroke={CHART.forecast}
              strokeWidth={2}
              strokeDasharray="6 4"
              dot={medianDotFor(visible)}
              activeDot={MEDIAN_DOT_ACTIVE}
              isAnimationActive={false}
            />
            <ReferenceLine
              x={detail.base_date}
              stroke={CHART.muted}
              strokeDasharray="2 3"
              label={{ value: "Phiên gần nhất", position: "insideTopRight", fill: CHART.muted, fontSize: 12 }}
            />
            {showBrush ? (
              <Brush
                key={`${range?.id ?? "all"}-${brushToken}`}
                dataKey="date"
                height={36}
                travellerWidth={10}
                startIndex={start}
                endIndex={end}
                onChange={(next) => setWin({ start: next.startIndex, end: next.endIndex })}
                tickFormatter={(value: string) => formatDate(value)}
                stroke={CHART.muted}
                fill={CHART.surface}
                ariaLabel={`Chọn đoạn đang xem: từ ${formatDate(data[start].date)} đến ${formatDate(
                  data[end].date,
                )}. Dùng phím mũi tên trái, phải để dịch đầu này.`}
              >
                <ComposedChart>
                  <Line dataKey="price" stroke={CHART.muted} strokeWidth={1} dot={false} isAnimationActive={false} />
                  <Line dataKey="median" stroke={CHART.forecast} strokeWidth={1} dot={false} isAnimationActive={false} />
                </ComposedChart>
              </Brush>
            ) : null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {showBrush ? (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted">
            Phóng to: kéo hai đầu thanh dưới biểu đồ, hoặc dùng nút bên cạnh. Bàn phím: Tab tới một đầu thanh rồi
            dùng phím ← →.
          </p>
          <div role="group" aria-label="Phóng to biểu đồ" className="flex gap-1">
            <button
              type="button"
              onClick={zoomIn}
              disabled={visible <= MIN_WINDOW}
              className="rounded-md border border-line px-3 py-1.5 text-sm text-price transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50"
            >
              Phóng to
            </button>
            <button
              type="button"
              onClick={zoomOut}
              disabled={!zoomed}
              className="rounded-md border border-line px-3 py-1.5 text-sm text-price transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50"
            >
              Thu nhỏ
            </button>
            <button
              type="button"
              onClick={() => setWindowFromButton(null)}
              disabled={!zoomed}
              className="rounded-md border border-line px-3 py-1.5 text-sm text-price transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50"
            >
              Đặt lại
            </button>
          </div>
        </div>
      ) : null}
      {forecastCut ? (
        <p role="status" className="mt-2 text-sm text-warn-fg">
          Một phần 7 phiên dự báo đang nằm ngoài đoạn đang xem. Bấm “Đặt lại” để xem lại cả mốc.
        </p>
      ) : null}

      <ul aria-label="Chú thích biểu đồ" className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted">
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-0.5 w-4 bg-price" />
          Giá thực tế (giá cuối phiên)
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="relative inline-block w-5 border-t-2 border-dashed border-forecast">
            <span className="absolute -top-[5px] left-1/2 size-2 -translate-x-1/2 rounded-full bg-median-dot" />
          </span>
          Trung vị dự báo từng phiên (chấm đỏ là mức giữa, không có nghĩa là giảm)
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-3 w-4 rounded-sm bg-band" />
          Khoảng 80% (q10–q90)
        </li>
      </ul>
    </section>
  );
}
