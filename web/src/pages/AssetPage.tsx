import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { isAssetId } from "../api/types";
import type { AssetId } from "../api/types";
import { useForecast, useHistory } from "../api/hooks";
import { ChatPanel } from "../components/ChatPanel";
import { FanChart } from "../components/FanChart";
import { PriceRange } from "../components/PriceRange";
import { ProbabilityBadge } from "../components/ProbabilityBadge";
import { QuantileTable } from "../components/QuantileTable";
import { ReturnFanChart } from "../components/ReturnFanChart";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/StateViews";
import { RollBadge, SampleBadge, StaleBadge } from "../components/StatusBadges";
import { CurrencyToggle, HorizonPicker, ModeToggle } from "../components/Toggles";
import { ASSETS } from "../lib/assets";
import { buildFanData, buildReturnFanData } from "../lib/chartData";
import { formatDate, formatDateTimeVn, formatNumber, formatPrice } from "../lib/format";
import {
  edgeFromReturns,
  findHorizon,
  isStaleByDate,
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
  const { mode, currency, setMode, setCurrency } = useSettings();
  const [horizonDays, setHorizonDays] = useState<number>(7);
  const forecast = useForecast(asset);
  const history = useHistory(asset);
  const detail = forecast.data;

  const fanData = useMemo(
    () => (detail ? buildFanData(asset, detail, history.data?.points, currency) : []),
    [asset, detail, history.data, currency],
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
          <CurrencyToggle value={currency} onChange={setCurrency} />
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
            />

            {history.isError ? (
              <EmptyBlock title="Chưa có lịch sử giá">
                Biểu đồ dưới đây chỉ vẽ phần dự báo vì API chưa trả lịch sử giá.
              </EmptyBlock>
            ) : null}
            <FanChart asset={asset} currency={currency} data={fanData} baseDate={detail.base_date} />

            {mode === "advanced" ? (
              <>
                <ReturnFanChart data={returnFan} />
                <QuantileTable asset={asset} detail={detail} currency={currency} />
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
}: {
  asset: AssetId;
  detail: NonNullable<ReturnType<typeof useForecast>["data"]>;
  horizonDays: number;
  onHorizonChange: (h: number) => void;
  currency: "USD" | "VND";
  advanced: boolean;
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

  return (
    <section aria-label="Tóm tắt dự báo" className="rounded-lg border border-line bg-white p-5">
      <div className="flex flex-wrap items-center gap-2">
        {detail.is_sample ? <SampleBadge /> : null}
        {stale ? <StaleBadge sources={detail.stale_sources} /> : null}
        {detail.roll_in_horizon ? <RollBadge /> : null}
      </div>

      <p className="tabular mt-3 text-3xl font-bold">
        {formatPrice(asset, lastDisplay, currency)}{" "}
        <span className="text-base font-normal text-muted">{displayUnit(asset, currency)}</span>
      </p>
      <p className="text-xs text-muted">
        Giá cuối ngày {formatDate(detail.base_date)} · tỷ giá USD/VND {formatNumber(detail.fx.usd_vnd)} (
        {formatDate(detail.fx.date)})
      </p>

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
        <PriceRange
          asset={asset}
          currency={currency}
          usdVnd={detail.fx.usd_vnd}
          low={horizon.prices[i10]}
          mid={horizon.prices[i50]}
          high={horizon.prices[i90]}
          horizonDays={horizon.h}
        />
      </div>

      <p className="mt-4 text-xs text-muted">
        Dự báo tạo lúc {formatDateTimeVn(detail.created_at)} · mô hình {detail.model_version}
        {advanced ? ` · chuỗi mục tiêu ${detail.target_series}` : ""}
      </p>
    </section>
  );
}

function Notes({ asset, detail }: { asset: AssetId; detail: NonNullable<ReturnType<typeof useForecast>["data"]> }) {
  const meta = ASSETS[asset];
  return (
    <section aria-label="Lưu ý" className="space-y-1 text-xs text-muted">
      {meta.note ? <p>{meta.note}</p> : null}
      {detail.roll_in_horizon ? (
        <p>Kỳ dự báo chứa ngày đáo hạn hợp đồng tương lai, giá có thể nhảy khi chuyển hợp đồng.</p>
      ) : null}
      {detail.is_sample ? <p>Số liệu trên trang này là dữ liệu mẫu, không phải dự báo thật.</p> : null}
      <p>{detail.disclaimer}</p>
    </section>
  );
}
