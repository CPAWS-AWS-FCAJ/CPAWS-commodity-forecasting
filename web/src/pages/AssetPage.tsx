import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { config } from "../api/config";
import { isAssetId } from "../api/types";
import type { AssetId } from "../api/types";
import { useForecast, useHistory } from "../api/hooks";
import { ChatPanel } from "../components/ChatPanel";
import { FanChart } from "../components/FanChart";
import { PriceRange } from "../components/PriceRange";
import { ProbabilityBadge } from "../components/ProbabilityBadge";
import { ReturnRange } from "../components/ReturnRange";
import { QuantileTable } from "../components/QuantileTable";
import { ReturnFanChart } from "../components/ReturnFanChart";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/StateViews";
import { BaselineBadge, RollBadge, SampleBadge, StaleBadge } from "../components/StatusBadges";
import { CurrencyToggle, HorizonPicker, ModeToggle } from "../components/Toggles";
import { ASSETS, isPriceHidden } from "../lib/assets";
import { buildFanData, buildReturnFanData } from "../lib/chartData";
import { formatDate, formatDateTimeVn, formatNumber, formatPrice } from "../lib/format";
import {
  BASELINE_Q252,
  edgeFromReturns,
  findHorizon,
  isStaleByDate,
  modelDisplayName,
  todayInVietnam,
} from "../lib/forecast";
import { useSettings } from "../lib/settings";
import { convertPrice, displayUnit } from "../lib/units";
import NotFound from "./NotFound";

const BASIC_HORIZONS = [1, 3, 7] as const;

export default function AssetPage() {
  const { id } = useParams();
  if (!isAssetId(id)) return <NotFound />;
  return <AssetContent asset={id} />;
}

function AssetContent({ asset }: { asset: AssetId }) {
  const meta = ASSETS[asset];
  // Vàng/bạc có thể ẩn giá bằng VITE_SHOW_METAL_PRICES=false (ADR-0005)
  const hidePrice = isPriceHidden(asset);
  const { mode, currency, setMode, setCurrency } = useSettings();
  const [horizonDays, setHorizonDays] = useState<number>(7);
  const forecast = useForecast(asset);
  const history = useHistory(asset);
  const detail = forecast.data;

  const fanData = useMemo(
    () => (detail && !hidePrice ? buildFanData(asset, detail, history.data?.points, currency) : []),
    [asset, detail, history.data, currency, hidePrice],
  );
  const returnFan = useMemo(() => (detail ? buildReturnFanData(detail) : []), [detail]);

  return (
    <div>
      <p className="text-sm">
        <Link to="/" className="text-forecast hover:underline">
          ← Tất cả sản phẩm
        </Link>
      </p>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{meta.name}</h1>
        <div className="flex flex-wrap gap-2">
          <ModeToggle value={mode} onChange={setMode} />
          {hidePrice ? null : <CurrencyToggle value={currency} onChange={setCurrency} />}
        </div>
      </div>

      {forecast.isPending ? (
        <div className="mt-4">
          <LoadingBlock label="Đang tải dự báo…" />
        </div>
      ) : null}
      {forecast.isError ? (
        <div className="mt-4">
          <ErrorBlock
            message={
              forecast.error.message
            }
            onRetry={() => void forecast.refetch()}
          />
        </div>
      ) : null}

      {detail ? (
        <div className="mt-4 grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-6">
            <Summary
              asset={asset}
              detail={detail}
              horizonDays={horizonDays}
              onHorizonChange={setHorizonDays}
              currency={currency}
              advanced={mode === "advanced"}
              hidePrice={hidePrice}
            />

            {!hidePrice && (!config.historyAvailable || history.isError) ? (
              <EmptyBlock title="Chưa có lịch sử giá">
                Biểu đồ dưới đây chỉ vẽ phần dự báo vì API chưa có endpoint lịch sử giá.
              </EmptyBlock>
            ) : null}
            {hidePrice ? (
              mode === "advanced" ? null : <ReturnFanChart data={returnFan} />
            ) : (
              <FanChart asset={asset} currency={currency} data={fanData} baseDate={detail.base_date} />
            )}

            {mode === "advanced" ? (
              <>
                <ReturnFanChart data={returnFan} />
                <QuantileTable asset={asset} detail={detail} currency={currency} showPrices={!hidePrice} />
                <EmptyBlock title="Tín hiệu ngoài giá (GPR, OVX/GVZ, lịch FOMC/OPEC+)">
                  Biểu đồ nhỏ 90 ngày sẽ có khi bảng tín hiệu theo ngày và endpoint tương ứng sẵn sàng.
                </EmptyBlock>
              </>
            ) : null}

            <EmptyBlock title="Độ chính xác 4 tuần gần nhất">
              Chưa có số liệu chạy thật. Xem trang{" "}
              <Link to="/accuracy" className="text-forecast underline">
                Độ chính xác
              </Link>
              .
            </EmptyBlock>

            <Notes asset={asset} detail={detail} />
          </div>
          <div className="lg:sticky lg:top-4 lg:self-start">
            <ChatPanel assetName={meta.name} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Summary({
  asset,
  detail,
  horizonDays,
  onHorizonChange,
  currency,
  advanced,
  hidePrice,
}: {
  asset: AssetId;
  detail: NonNullable<ReturnType<typeof useForecast>["data"]>;
  horizonDays: number;
  onHorizonChange: (h: number) => void;
  currency: "USD" | "VND";
  advanced: boolean;
  hidePrice: boolean;
}) {
  const horizon = findHorizon(detail, horizonDays) ?? detail.horizons[detail.horizons.length - 1];
  const options = BASIC_HORIZONS.filter((h) => findHorizon(detail, h));
  const edge = edgeFromReturns(detail.quantile_levels, horizon.returns);
  const i10 = detail.quantile_levels.findIndex((l) => Math.abs(l - 0.1) < 1e-9);
  const i50 = detail.quantile_levels.findIndex((l) => Math.abs(l - 0.5) < 1e-9);
  const i90 = detail.quantile_levels.findIndex((l) => Math.abs(l - 0.9) < 1e-9);

  const stale =
    detail.stale_sources.length > 0 ||
    isStaleByDate(detail.base_date, todayInVietnam(), detail.is_sample);
  const lastDisplay = convertPrice(asset, detail.last_price, currency, detail.fx.usd_vnd);
  // created_at và model_version có thể chưa có trong phản hồi API (PR #22)
  const footer = [
    detail.created_at ? `Dự báo tạo lúc ${formatDateTimeVn(detail.created_at)}` : null,
    detail.model_version ? modelFooter(detail.model_version) : null,
    advanced ? `chuỗi mục tiêu ${detail.target_series}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <section aria-label="Tóm tắt dự báo" className="rounded-lg border border-line bg-white p-5">
      <div className="flex flex-wrap items-center gap-2">
        {detail.is_sample ? <SampleBadge /> : null}
        {detail.model_version === BASELINE_Q252 ? <BaselineBadge /> : null}
        {stale ? <StaleBadge sources={detail.stale_sources} /> : null}
        {detail.roll_in_horizon ? <RollBadge /> : null}
      </div>

      {hidePrice ? (
        <p className="mt-3 text-sm text-muted">
          Dữ liệu đến ngày {formatDate(detail.base_date)}. Giá {ASSETS[asset].name.toLowerCase()} đang được ẩn;
          chỉ hiển thị % thay đổi và xác suất tăng.
        </p>
      ) : (
        <>
          <p className="tabular mt-3 text-3xl font-bold">
            {formatPrice(asset, lastDisplay, currency)}{" "}
            <span className="text-base font-normal text-muted">{displayUnit(asset, currency)}</span>
          </p>
          <p className="text-xs text-muted">
            Giá cuối ngày {formatDate(detail.base_date)} · tỷ giá USD/VND {formatNumber(detail.fx.usd_vnd)} (
            {formatDate(detail.fx.date)})
          </p>
        </>
      )}

      <div className="mt-4">
        <HorizonPicker value={horizon.h === horizonDays ? horizonDays : horizon.h} options={options} onChange={onHorizonChange} />
      </div>

      <div className="mt-5 grid gap-6 sm:grid-cols-2">
        <ProbabilityBadge
          probUp={horizon.prob_up}
          zeroBelowQ10={edge.zeroBelowQ10}
          zeroAboveQ90={edge.zeroAboveQ90}
          horizonDays={horizon.h}
        />
        {hidePrice ? (
          <ReturnRange
            low={horizon.returns[i10]}
            mid={horizon.returns[i50]}
            high={horizon.returns[i90]}
            horizonDays={horizon.h}
          />
        ) : (
          <PriceRange
            asset={asset}
            currency={currency}
            usdVnd={detail.fx.usd_vnd}
            low={horizon.prices[i10]}
            mid={horizon.prices[i50]}
            high={horizon.prices[i90]}
            horizonDays={horizon.h}
          />
        )}
      </div>

      {footer ? <p className="mt-4 text-xs text-muted">{footer}</p> : null}
    </section>
  );
}

/** "Mốc thống kê 252 phiên (baseline-q252)" hoặc "mô hình <mã>" khi không có tên riêng. */
function modelFooter(version: string): string {
  const name = modelDisplayName(version);
  return name ? `${name} (${version})` : `mô hình ${version}`;
}

function Notes({ asset, detail }: { asset: AssetId; detail: NonNullable<ReturnType<typeof useForecast>["data"]> }) {
  const meta = ASSETS[asset];
  return (
    <section aria-label="Lưu ý" className="space-y-1 text-xs text-muted">
      {meta.note ? <p>{meta.note}</p> : null}
      {isPriceHidden(asset) ? <p>Giá vàng và bạc đang được ẩn; trang này chỉ hiển thị % thay đổi và xác suất tăng.</p> : null}
      {detail.roll_in_horizon ? (
        <p>Kỳ dự báo chứa ngày đáo hạn hợp đồng tương lai, giá có thể nhảy khi chuyển hợp đồng.</p>
      ) : null}
      {detail.is_sample ? <p>Số liệu trên trang này là dữ liệu mẫu, không phải dự báo thật.</p> : null}
      {detail.model_version === BASELINE_Q252 ? (
        <p>
          Dự báo hiện dùng mốc thống kê: khoảng dự báo lấy từ phân phối return của 252 phiên giao dịch gần nhất
          (khoảng 1 năm), chưa dùng mô hình học máy.
        </p>
      ) : null}
      <p>{detail.disclaimer}</p>
    </section>
  );
}
