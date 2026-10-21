import type { AssetId, Currency } from "../api/types";
import { formatNumber, formatPrice } from "../lib/format";
import { convertPrice, displayUnit } from "../lib/units";

interface Props {
  asset: AssetId;
  currency: Currency;
  usdVnd: number;
  /** Giá USD theo đơn vị gốc của tài sản. */
  low: number;
  mid: number;
  high: number;
  horizonDays: number;
}

function range(asset: AssetId, currency: Currency, usdVnd: number, low: number, high: number) {
  const a = convertPrice(asset, low, currency, usdVnd);
  const b = convertPrice(asset, high, currency, usdVnd);
  return `${formatPrice(asset, a, currency)}–${formatPrice(asset, b, currency)} ${displayUnit(asset, currency)}`;
}

/** Khoảng giá nhiều khả năng (khoảng 80%); dòng phụ hiện đơn vị còn lại. */
export function PriceRange({ asset, currency, usdVnd, low, mid, high, horizonDays }: Props) {
  const other: Currency = currency === "USD" ? "VND" : "USD";
  return (
    <div>
      <p className="text-sm text-muted">Sau {horizonDays} ngày, nhiều khả năng trong khoảng (80%)</p>
      <p className="tabular mt-1 text-xl font-semibold">{range(asset, currency, usdVnd, low, high)}</p>
      <p className="tabular mt-1 text-sm text-muted">
        Giá trung vị: {formatPrice(asset, convertPrice(asset, mid, currency, usdVnd), currency)}{" "}
        {displayUnit(asset, currency)}. Cùng khoảng theo {other}: {range(asset, other, usdVnd, low, high)}
      </p>
      {currency === "VND" ? (
        <p className="mt-1 text-xs text-muted">
          Tỷ giá USD/VND {formatNumber(usdVnd)}.
          {asset === "gold"
            ? " Giá vàng quy đổi không phải giá vàng miếng trong nước (chưa gồm thuế, phí, chênh lệch thị trường)."
            : ""}
        </p>
      ) : null}
    </div>
  );
}
