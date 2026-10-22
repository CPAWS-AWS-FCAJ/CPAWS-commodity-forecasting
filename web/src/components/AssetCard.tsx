import { Link } from "react-router-dom";
import type { ForecastSummary } from "../api/types";
import { ASSETS } from "../lib/assets";
import { formatDate, formatPrice, formatReturnPercent } from "../lib/format";
import { ProbabilityBadge } from "./ProbabilityBadge";
import { RollBadge, SampleBadge, StaleBadge } from "./StatusBadges";

interface Props {
  item: ForecastSummary;
  /** Ẩn giá (vàng/bạc khi VITE_SHOW_METAL_PRICES=false): chỉ hiện % thay đổi và xác suất tăng. */
  hidePrice?: boolean;
}

/** Thẻ sản phẩm ở trang chủ: giá cuối, khả năng tăng/giảm 7 ngày và khoảng giá 80%. */
export function AssetCard({ item, hidePrice = false }: Props) {
  const meta = ASSETS[item.asset];
  const unit = item.price_unit;
  return (
    <Link
      to={`/asset/${item.asset}`}
      className="block h-full rounded-lg border border-line bg-white p-5 transition hover:border-forecast"
    >
      <h2 className="text-lg font-semibold">{meta.name}</h2>
      <div className="mt-1 flex min-h-12 flex-wrap content-start gap-1">
        {item.is_sample ? <SampleBadge /> : null}
        {item.stale ? <StaleBadge /> : null}
        {item.roll_in_horizon ? <RollBadge /> : null}
      </div>
      {hidePrice ? (
        <p className="mt-2 text-xs text-muted">
          Dữ liệu đến ngày {formatDate(item.base_date)} · hiển thị theo % thay đổi
        </p>
      ) : (
        <>
          <p className="tabular mt-2 text-2xl font-semibold">
            {formatPrice(item.asset, item.last_price, "USD")}{" "}
            <span className="text-sm font-normal text-muted">{unit}</span>
          </p>
          <p className="text-xs text-muted">Giá cuối ngày {formatDate(item.base_date)}</p>
        </>
      )}

      <div className="mt-4">
        <ProbabilityBadge
          probUp={item.h7.prob_up}
          zeroBelowQ10={item.h7.p10 > item.last_price}
          zeroAboveQ90={item.h7.p90 < item.last_price}
          horizonDays={7}
        />
      </div>
      {hidePrice ? (
        <p className="tabular mt-4 text-sm">
          Thay đổi 80% sau 7 ngày:{" "}
          <span className="font-medium">
            {formatReturnPercent(Math.log(item.h7.p10 / item.last_price))} đến{" "}
            {formatReturnPercent(Math.log(item.h7.p90 / item.last_price))}
          </span>
        </p>
      ) : (
        <p className="tabular mt-4 text-sm">
          Khoảng giá 80% sau 7 ngày:{" "}
          <span className="font-medium">
            {formatPrice(item.asset, item.h7.p10, "USD")}–{formatPrice(item.asset, item.h7.p90, "USD")} {unit}
          </span>
        </p>
      )}
      <p className="mt-3 text-sm font-medium text-forecast">Xem chi tiết →</p>
    </Link>
  );
}
