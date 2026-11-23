import { useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { usePriceOverview } from "../api/hooks";
import { ASSET_IDS } from "../api/types";
import type { AssetId, Currency, ForecastDetailWithHistory } from "../api/types";
import { PriceTrendChart } from "../components/PriceTrendChart";
import { ProbabilityBadge } from "../components/ProbabilityBadge";
import { RangePicker } from "../components/RangePicker";
import { SourceNote } from "../components/SourceNote";
import { Swap } from "../components/Swap";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/StateViews";
import { BaselineBadge, SampleBadge, StaleBadge } from "../components/StatusBadges";
import { CurrencyToggle } from "../components/Toggles";
import { ASSETS, isPriceHidden } from "../lib/assets";
import { formatDate, formatNumber, formatPrice, formatReturnPercent } from "../lib/format";
import { BASELINE_Q252, findHorizon, horizonView } from "../lib/forecast";
import {
  DIRECTION_ARROW,
  DIRECTION_CLASS,
  DIRECTION_WORD,
  OVERVIEW_RANGES,
  defaultRange,
  formatChangeMagnitude,
  isRangeAvailable,
  lastSessionChange,
  rangeStats,
  sliceRange,
} from "../lib/priceOverview";
import type { HistoryRange, PriceChange } from "../lib/priceOverview";
import { matchesMedia, REDUCED_MOTION } from "../lib/media";
import { useSettings } from "../lib/settings";
import { GOLD_VND_NOTE, METAL_PRICE_NOTE } from "../lib/source";
import { convertPrice, displayUnit, isMetal } from "../lib/units";

/** Viền ô đang chọn theo màu nhận diện sản phẩm (cùng màu đường giá trên biểu đồ). */
const SELECTED_BORDER: Record<AssetId, string> = {
  gold: "border-gold ring-1 ring-gold",
  silver: "border-silver ring-1 ring-silver",
  brent: "border-brent ring-1 ring-brent",
  wti: "border-wti ring-1 ring-wti",
};

/** Mặc định xem 1 tháng; chưa đủ dữ liệu thì mốc lớn nhất còn đủ. */
const DEFAULT_RANGE_SESSIONS = 21;

function ChangeText({ change, suffix }: { change: PriceChange | null; suffix: string }) {
  if (!change) return <span className="text-muted">Chưa đủ dữ liệu để so sánh</span>;
  return (
    <span className={DIRECTION_CLASS[change.direction]}>
      <span aria-hidden="true">{DIRECTION_ARROW[change.direction]} </span>
      {DIRECTION_WORD[change.direction]}{" "}
      <span className="tabular">{formatChangeMagnitude(change.ratio)}</span>{" "}
      <span className="text-muted">{suffix}</span>
    </span>
  );
}

interface TileProps {
  asset: AssetId;
  detail: ForecastDetailWithHistory | undefined;
  isPending: boolean;
  isError: boolean;
  selected: boolean;
  currency: Currency;
  onSelect: (asset: AssetId) => void;
}

/** Ô giá một tài sản: tên, giá cuối phiên, thay đổi so với phiên trước. Bấm để xem biểu đồ. */
function PriceTile({ asset, detail, isPending, isError, selected, currency, onSelect }: TileProps) {
  const hidden = isPriceHidden(asset);
  const change = detail ? lastSessionChange(detail.price_history) : null;
  const price = detail ? convertPrice(asset, detail.last_price, currency, detail.fx.usd_vnd) : null;
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={() => onSelect(asset)}
      className={`lift block h-full w-full rounded-lg border bg-surface p-4 text-left ${
        selected ? SELECTED_BORDER[asset] : "border-line hover:border-muted"
      }`}
    >
      <span className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{ASSETS[asset].name}</span>
        {detail?.is_sample ? <SampleBadge /> : null}
        {detail && detail.stale_sources.length > 0 ? <StaleBadge sources={detail.stale_sources} /> : null}
      </span>
      {isPending ? (
        // Khung chờ cùng cỡ dòng giá; chữ "Đang tải…" giữ cho trình đọc màn hình
        <span className="mt-2 block">
          <span className="sr-only">Đang tải…</span>
          <span aria-hidden="true" className="skeleton block h-8 w-32" />
          <span aria-hidden="true" className="skeleton mt-2 block h-4 w-40 max-w-full" />
        </span>
      ) : null}
      {isError ? <span className="mt-3 block text-sm text-down">Không tải được dữ liệu</span> : null}
      {detail ? (
        <>
          {hidden || price === null ? (
            <span className="mt-3 block text-sm text-muted">Giá đang được ẩn, chỉ hiện % thay đổi</span>
          ) : (
            <span className="tabular mt-2 block text-2xl font-semibold">
              <Swap value={currency}>
                {formatPrice(asset, price, currency)}{" "}
                <span className="text-sm font-normal text-muted">{displayUnit(asset, currency)}</span>
              </Swap>
            </span>
          )}
          <span className="mt-1 block text-sm">
            <ChangeText
              change={change}
              suffix={change ? `so với phiên ${formatDate(change.fromDate).slice(0, 5)}` : ""}
            />
          </span>
          <span className="mt-2 block text-xs text-muted">Giá cuối phiên {formatDate(detail.base_date)}</span>
        </>
      ) : null}
    </button>
  );
}

interface PanelProps {
  asset: AssetId;
  detail: ForecastDetailWithHistory;
  currency: Currency;
  /** Mốc người xem đã chọn; undefined = mặc định. */
  chosen: HistoryRange["id"] | undefined;
  onRangeChange: (range: HistoryRange) => void;
}

/** Biểu đồ giá cuối phiên của tài sản đang chọn và số liệu của khoảng thời gian. */
function TrendPanel({ asset, detail, currency, chosen, onRangeChange }: PanelProps) {
  const name = ASSETS[asset].name;
  const unit = displayUnit(asset, currency);
  const pointCount = detail.price_history.length;
  // Mốc đã chọn mà tài sản này chưa đủ dữ liệu thì về mặc định của tài sản này
  const chosenRange = OVERVIEW_RANGES.find((item) => item.id === chosen);
  const range =
    chosenRange && isRangeAvailable(chosenRange, pointCount)
      ? chosenRange
      : defaultRange(OVERVIEW_RANGES, pointCount, DEFAULT_RANGE_SESSIONS) ??
        defaultRange(OVERVIEW_RANGES, pointCount, Number.POSITIVE_INFINITY);
  const points = sliceRange(detail.price_history, range);
  const stats = rangeStats(points);
  const toDisplay = (usd: number) => convertPrice(asset, usd, currency, detail.fx.usd_vnd);
  const data = points.map((point) => ({ date: point.base_date, price: toDisplay(point.last_price) }));
  const first = detail.price_history[0];

  return (
    <section aria-labelledby="trend-title" className="rounded-lg border border-line bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="trend-title" className="text-lg font-semibold">
            {name}
          </h2>
          <p className="text-sm text-muted">Giá cuối phiên, {unit}</p>
        </div>
        <RangePicker ranges={OVERVIEW_RANGES} value={range?.id ?? null} pointCount={pointCount} onChange={onRangeChange} />
      </div>

      <div className="mt-4">
        {data.length >= 2 ? (
          <PriceTrendChart
            asset={asset}
            currency={currency}
            data={data}
            label={`Giá cuối phiên ${name.toLowerCase()} (${unit}), ${range ? range.label : `${pointCount} phiên`}`}
          />
        ) : (
          <EmptyBlock title="Chưa đủ dữ liệu để vẽ biểu đồ">
            Cần ít nhất 2 phiên có giá. Hệ thống ghi thêm một phiên mỗi tối thứ Ba đến thứ Bảy.
          </EmptyBlock>
        )}
      </div>

      {stats ? (
        <dl className="tabular mt-4 grid grid-cols-1 gap-3 border-t border-line pt-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-muted">Cao nhất</dt>
            <dd className="mt-0.5 font-medium">
              {formatPrice(asset, toDisplay(stats.high), currency)} {unit}
            </dd>
          </div>
          <div>
            <dt className="text-muted">Thấp nhất</dt>
            <dd className="mt-0.5 font-medium">
              {formatPrice(asset, toDisplay(stats.low), currency)} {unit}
            </dd>
          </div>
          <div>
            <dt className="text-muted">Thay đổi trong khoảng</dt>
            <dd className="mt-0.5 font-medium">
              <ChangeText
                change={stats.change}
                suffix={stats.change ? `từ ${formatDate(stats.change.fromDate)}` : ""}
              />
            </dd>
          </div>
        </dl>
      ) : null}
      {first ? (
        <p className="mt-3 text-xs text-muted">
          Dữ liệu từ {formatDate(first.base_date)}, {formatNumber(pointCount)} phiên
          {range ? "" : " (chưa đủ cho mốc ngắn nhất nên hiện toàn bộ)"}. Trục giá không bắt đầu từ 0.
        </p>
      ) : null}
    </section>
  );
}

/** Tóm tắt dự báo 7 phiên tới của tài sản đang chọn; chi tiết ở trang sản phẩm. */
function ForecastAside({ asset, detail, currency }: { asset: AssetId; detail: ForecastDetailWithHistory; currency: Currency }) {
  const horizon = findHorizon(detail, 7);
  const view = horizon ? horizonView(detail, horizon) : null;
  const hidden = isPriceHidden(asset);
  const unit = displayUnit(asset, currency);
  const toDisplay = (usd: number) => convertPrice(asset, usd, currency, detail.fx.usd_vnd);
  return (
    <aside aria-labelledby="aside-title" className="self-start rounded-lg border border-line bg-surface p-4 sm:p-5">
      <h2 id="aside-title" className="text-lg font-semibold">
        7 phiên tới
      </h2>
      <div className="mt-2 flex flex-wrap gap-1">
        {detail.model_version === BASELINE_Q252 ? <BaselineBadge /> : null}
        {detail.is_sample ? <SampleBadge /> : null}
      </div>
      {view ? (
        <>
          <div className="mt-4">
            <ProbabilityBadge probUp={view.probUp} horizonDays={7} />
          </div>
          <p className="tabular mt-4 text-sm">
            {hidden ? "Thay đổi 80% sau 7 phiên: " : "Khoảng giá 80% sau 7 phiên: "}
            <Swap value={currency} className="font-medium">
              {hidden
                ? `${formatReturnPercent(view.returnLow)} đến ${formatReturnPercent(view.returnHigh)}`
                : `${formatPrice(asset, toDisplay(view.low), currency)}–${formatPrice(asset, toDisplay(view.high), currency)} ${unit}`}
            </Swap>
          </p>
        </>
      ) : (
        <p className="mt-4 text-sm text-muted">Chưa có dự báo 7 phiên cho tài sản này.</p>
      )}
      <Link
        to={`/asset/${asset}`}
        className="mt-5 inline-block rounded-md border border-line px-3 py-1.5 text-sm font-medium text-forecast transition-colors hover:bg-surface-muted pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center"
      >
        Xem dự báo chi tiết
      </Link>
    </aside>
  );
}

export default function Overview() {
  const results = usePriceOverview();
  const { currency, setCurrency } = useSettings();
  const defaultAsset: AssetId = isPriceHidden("gold") ? "brent" : "gold";
  const [selected, setSelected] = useState<AssetId>(defaultAsset);
  const [chosenRange, setChosenRange] = useState<HistoryRange["id"] | undefined>(undefined);
  const chartRef = useRef<HTMLDivElement>(null);

  // Điện thoại: 4 thẻ xếp dọc nên biểu đồ nằm dưới màn hình; chọn thẻ thì cuộn tới biểu đồ để thấy thay
  // đổi. Máy tính (biểu đồ đã trong màn hình) không cuộn.
  const selectAsset = (asset: AssetId) => {
    setSelected(asset);
    const chart = chartRef.current;
    if (!chart) return;
    const top = chart.getBoundingClientRect().top;
    if (top >= 0 && top <= window.innerHeight * 0.6) return;
    chart.scrollIntoView?.({ block: "start", behavior: matchesMedia(REDUCED_MOTION) ? "auto" : "smooth" });
  };

  const byAsset = useMemo(() => {
    const map = new Map<AssetId, (typeof results)[number]>();
    ASSET_IDS.forEach((asset, index) => map.set(asset, results[index]));
    return map;
  }, [results]);

  const current = byAsset.get(selected);
  const detail = current?.data;
  const anyMetalShown = ASSET_IDS.some((asset) => isMetal(asset) && !isPriceHidden(asset));
  const fx = results.find((result) => result.data)?.data?.fx;

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Tổng quan giá</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Giá cuối phiên của vàng, bạc và dầu theo dữ liệu hệ thống ghi mỗi ngày giao dịch. Chọn một sản phẩm
            để xem biến động gần đây; dự báo chi tiết nằm ở trang của từng sản phẩm.
          </p>
        </div>
        <CurrencyToggle value={currency} onChange={setCurrency} />
      </div>

      <ul className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {ASSET_IDS.map((asset, index) => {
          const result = byAsset.get(asset);
          return (
            <li key={asset} className="stagger-item h-full" style={{ "--i": index } as CSSProperties}>
              <PriceTile
                asset={asset}
                detail={result?.data}
                isPending={result?.isPending ?? true}
                isError={result?.isError ?? false}
                selected={asset === selected}
                currency={currency}
                onSelect={selectAsset}
              />
            </li>
          );
        })}
      </ul>

      <div ref={chartRef} data-testid="overview-chart" className="mt-4 scroll-mt-20 lg:scroll-mt-6">
        {current?.isPending ? <LoadingBlock label="Đang tải giá…" shape="chart" /> : null}
        {current?.isError ? (
          <ErrorBlock message={current.error.message} onRetry={() => void current.refetch()} />
        ) : null}
        {detail ? (
          // Đổi sản phẩm: khối biểu đồ hiện lại (mờ dần) và đường giá vẽ lại một lần
          <div key={selected} className="animate-fade-in">
          {isPriceHidden(selected) ? (
            <div className="grid gap-4 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <EmptyBlock title={`Giá ${ASSETS[selected].name.toLowerCase()} đang được ẩn`}>
                  Trang này chỉ hiện % thay đổi của vàng và bạc. Xem khoảng thay đổi dự báo ở trang sản phẩm.
                </EmptyBlock>
              </div>
              <ForecastAside asset={selected} detail={detail} currency={currency} />
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <TrendPanel
                  asset={selected}
                  detail={detail}
                  currency={currency}
                  chosen={chosenRange}
                  onRangeChange={(next) => setChosenRange(next.id)}
                />
              </div>
              <ForecastAside asset={selected} detail={detail} currency={currency} />
            </div>
          )}
          </div>
        ) : null}
      </div>

      <div className="mt-4 space-y-1">
        <SourceNote />
        {anyMetalShown ? <p className="text-xs text-muted">{METAL_PRICE_NOTE}</p> : null}
        {currency === "VND" && fx ? (
          <p className="text-xs text-muted">
            Quy đổi VND theo tỷ giá USD/VND {formatNumber(fx.usd_vnd)} ngày {formatDate(fx.date)}, áp dụng cho mọi
            phiên trên trang này.
          </p>
        ) : null}
        {currency === "VND" && anyMetalShown ? <p className="text-xs text-muted">{GOLD_VND_NOTE}</p> : null}
      </div>
    </div>
  );
}
