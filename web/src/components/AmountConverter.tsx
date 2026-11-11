import { useId, useState } from "react";
import type { AssetId, ForecastDetail } from "../api/types";
import {
  AMOUNT_NOTE,
  MAX_AMOUNT_VND,
  MIN_AMOUNT_VND,
  amountRange,
  parseAmountInput,
} from "../lib/amount";
import type { AmountParse } from "../lib/amount";
import { ASSETS } from "../lib/assets";
import { findHorizon, horizonView } from "../lib/forecast";
import { formatDate, formatNumber, formatReturnPercent } from "../lib/format";
import { isMetal } from "../lib/units";

interface Props {
  asset: AssetId;
  detail: ForecastDetail;
  /** Số phiên đang chọn ở phần tóm tắt / dải thẻ. */
  horizonDays: number;
}

const ERROR_TEXT: Record<Exclude<AmountParse, { ok: true }>["reason"], string | null> = {
  empty: null,
  invalid: "Chỉ nhập số nguyên đồng, ví dụ 10.000.000.",
  too_small: `Số tiền tối thiểu ${formatNumber(MIN_AMOUNT_VND)} đồng.`,
  too_large: `Số tiền tối đa ${formatNumber(MAX_AMOUNT_VND)} đồng.`,
};

/**
 * Khối "Quy đổi ra số tiền" (ADR-0005 mục (2)): người xem nhập số tiền, web hiện giá trị giả định
 * `số tiền × exp(q)` tại q10, q50, q90 của h đang chọn. Chỉ dùng `returns` của API nên chạy được cả
 * khi ẩn giá vàng/bạc. Số tiền không lưu lại (không localStorage).
 */
export function AmountConverter({ asset, detail, horizonDays }: Props) {
  const inputId = useId();
  const errorId = useId();
  const [text, setText] = useState("");
  const horizon = findHorizon(detail, horizonDays) ?? detail.horizons[detail.horizons.length - 1];
  const view = horizonView(detail, horizon);
  const parsed = parseAmountInput(text);
  const error = parsed.ok ? null : ERROR_TEXT[parsed.reason];
  const range = parsed.ok ? amountRange(parsed.value, view.returnLow, view.returnMid, view.returnHigh) : null;
  const name = ASSETS[asset].name;
  const vnd = (value: number) => `${formatNumber(value)} đồng`;

  return (
    <section aria-labelledby={`${inputId}-title`} className="rounded-lg border border-line bg-white p-5">
      <h2 id={`${inputId}-title`} className="text-lg font-semibold">
        Quy đổi ra số tiền (giá trị giả định)
      </h2>
      <label htmlFor={inputId} className="mt-3 block text-sm">
        Số tiền (đồng)
      </label>
      <input
        id={inputId}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        placeholder="10.000.000"
        value={text}
        onChange={(event) => setText(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className="tabular mt-1 w-full max-w-xs rounded-md border border-line px-3 py-2 text-base"
      />
      {error ? (
        <p id={errorId} role="alert" className="mt-1 text-sm text-down">
          {error}
        </p>
      ) : null}

      <div aria-live="polite" className="mt-3 text-sm">
        {parsed.ok && range ? (
          <>
            <p>
              Nếu giá {name.toLowerCase()} thay đổi đúng theo dự báo, sau {view.h} phiên (phiên{" "}
              {formatDate(view.targetDate)}) {vnd(parsed.value)} có giá trị giả định:
            </p>
            <p className="tabular mt-2">
              <span className="text-muted">Khoảng 80%: </span>
              <strong>
                {formatNumber(range.low)} – {formatNumber(range.high)} đồng
              </strong>{" "}
              <span className="text-muted">
                ({formatReturnPercent(view.returnLow)} đến {formatReturnPercent(view.returnHigh)})
              </span>
            </p>
            <p className="tabular">
              <span className="text-muted">Mức giữa: </span>
              {vnd(range.mid)} <span className="text-muted">({formatReturnPercent(view.returnMid)})</span>
            </p>
          </>
        ) : (
          <p className="text-muted">Nhập số tiền để xem giá trị giả định sau {view.h} phiên.</p>
        )}
      </div>

      <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted">
        <li>
          Đây là giá trị giả định của số tiền đó nếu giá thay đổi đúng bằng phân vị dự báo; không phải số
          tiền đầu tư thực tế, không phải lợi nhuận thực nhận hay được bảo đảm. Mức bao phủ thực tế của
          khoảng 80% có thể khác 80%.
        </li>
        <li>Giả định tỷ giá USD/VND không đổi trong {view.h} phiên.</li>
        {isMetal(asset) ? (
          <li>Tính theo % thay đổi dự báo của chuỗi đại diện {detail.target_series}, không phải giá giao ngay.</li>
        ) : null}
        <li>{AMOUNT_NOTE}</li>
      </ul>
    </section>
  );
}
