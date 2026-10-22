import { formatReturnPercent } from "../lib/format";

interface Props {
  /** Log return tại q10, q50, q90 (số thập phân, ví dụ 0,01 = +1%). */
  low: number;
  mid: number;
  high: number;
  horizonDays: number;
}

/** Thay cho PriceRange khi ẩn giá (vàng/bạc, VITE_SHOW_METAL_PRICES=false): chỉ hiện % thay đổi. */
export function ReturnRange({ low, mid, high, horizonDays }: Props) {
  return (
    <div>
      <p className="text-sm text-muted">
        Sau {horizonDays} ngày, mức thay đổi nhiều khả năng nằm trong khoảng (80%)
      </p>
      <p className="tabular mt-1 text-xl font-semibold">
        {formatReturnPercent(low)} đến {formatReturnPercent(high)}
      </p>
      <p className="tabular mt-1 text-sm text-muted">
        Trung vị: {formatReturnPercent(mid)}. Đây là log return, không hiển thị giá.
      </p>
    </div>
  );
}
