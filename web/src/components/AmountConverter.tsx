import { useId, useState } from "react";
import type { ChangeEvent, ClipboardEvent, KeyboardEvent } from "react";
import type { AssetId, ForecastDetail } from "../api/types";
import {
  AMOUNT_NOTE,
  MAX_AMOUNT_DIGITS,
  MAX_AMOUNT_VND,
  MIN_AMOUNT_VND,
  amountInWords,
  amountRange,
  caretAfterDigits,
  editFromPaste,
  editFromTyping,
  groupDigits,
  parseAmountInput,
} from "../lib/amount";
import type { AmountEdit, AmountEditReject, AmountParse } from "../lib/amount";
import { ASSETS } from "../lib/assets";
import { findHorizon, horizonView } from "../lib/forecast";
import { formatDate, formatNumber, formatReturnPercent } from "../lib/format";
import { isMetal } from "../lib/units";
import { GUIDE_ANCHORS, GuideLink } from "./HowToRead";

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

/** Lý do một lần gõ/dán bị bỏ qua (ô giữ nguyên giá trị cũ). */
const REJECT_TEXT: Record<AmountEditReject, string> = {
  not_digit: "Chỉ nhận chữ số 0–9; dấu chấm phân cách nghìn tự thêm khi gõ.",
  too_long: `Tối đa ${MAX_AMOUNT_DIGITS} chữ số.`,
  decimal: "Chỉ nhận số nguyên đồng, ví dụ 10.000.000.",
};

const HINT = "Chỉ nhận chữ số; dấu chấm phân cách nghìn tự thêm khi gõ.";

/**
 * Khối "Quy đổi ra số tiền" (ADR-0005 mục (2)): người xem nhập số tiền, web hiện giá trị giả định
 * `số tiền × exp(q)` tại q10, q50, q90 của h đang chọn. Chỉ dùng `returns` của API nên chạy được cả
 * khi ẩn giá vàng/bạc. Số tiền không lưu lại (không localStorage).
 *
 * Ô nhập giữ chuỗi chữ số trong state và hiện bản có dấu chấm nhóm nghìn ("900.000.000") ngay khi gõ;
 * con trỏ đặt lại theo số chữ số đứng trước nó nên gõ/xóa ở giữa không bị nhảy về cuối.
 */
export function AmountConverter({ asset, detail, horizonDays }: Props) {
  const inputId = useId();
  const errorId = useId();
  const hintId = useId();
  const [digits, setDigits] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const text = groupDigits(digits);

  const horizon = findHorizon(detail, horizonDays) ?? detail.horizons[detail.horizons.length - 1];
  const view = horizonView(detail, horizon);
  const parsed = parseAmountInput(text);
  const error = parsed.ok ? null : ERROR_TEXT[parsed.reason];
  // Dưới mức tối thiểu là trạng thái khi đang gõ dở ("1", "10"…): nhắc nhẹ, không báo lỗi to
  const blocking = !parsed.ok && (parsed.reason === "too_large" || parsed.reason === "invalid");
  const range = parsed.ok ? amountRange(parsed.value, view.returnLow, view.returnMid, view.returnHigh) : null;
  const words = parsed.ok ? amountInWords(parsed.value) : null;
  const name = ASSETS[asset].name;
  const vnd = (value: number) => `${formatNumber(value)} đồng`;

  /**
   * Ghi thẳng giá trị đã định dạng vào DOM và đặt con trỏ trước khi React render lại: React thấy giá
   * trị trùng nên không ghi đè, con trỏ giữ đúng chỗ. Bị từ chối thì trả lại chuỗi cũ.
   */
  function apply(input: HTMLInputElement, edit: AmountEdit, rejectCaret: number) {
    if (!edit.ok) {
      input.value = text;
      if (document.activeElement === input) input.setSelectionRange(rejectCaret, rejectCaret);
      setNotice(REJECT_TEXT[edit.reason]);
      return;
    }
    const next = groupDigits(edit.digits);
    input.value = next;
    if (document.activeElement === input) {
      const caret = caretAfterDigits(next, edit.caretDigits);
      input.setSelectionRange(caret, caret);
    }
    setNotice(null);
    setDigits(edit.digits);
  }

  function onChange(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const raw = input.value;
    const caret = input.selectionStart ?? raw.length;
    const inserted = Math.max(0, raw.length - text.length);
    apply(input, editFromTyping(raw, caret), Math.max(0, caret - inserted));
  }

  function onPaste(event: ClipboardEvent<HTMLInputElement>) {
    event.preventDefault();
    const input = event.currentTarget;
    const start = input.selectionStart ?? text.length;
    const end = input.selectionEnd ?? start;
    apply(input, editFromPaste(text, start, end, event.clipboardData.getData("text")), start);
  }

  /** Xóa ngay sau/trước dấu chấm thì nhảy qua dấu chấm để xóa chữ số (dấu chấm tự thêm lại). */
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const { selectionStart: at, selectionEnd } = input;
    if (at === null || at !== selectionEnd) return;
    if (event.key === "Backspace" && at > 0 && input.value[at - 1] === ".") input.setSelectionRange(at - 1, at - 1);
    if (event.key === "Delete" && input.value[at] === ".") input.setSelectionRange(at + 1, at + 1);
  }

  const describedBy = [hintId, error ? errorId : null].filter(Boolean).join(" ");

  return (
    <section aria-labelledby={`${inputId}-title`} className="rounded-lg border border-line bg-surface p-5">
      <h2 id={`${inputId}-title`} className="text-lg font-semibold">
        Quy đổi ra số tiền (giá trị giả định)
      </h2>
      <label htmlFor={inputId} className="mt-3 block text-sm">
        Số tiền (đồng)
      </label>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
        <input
          id={inputId}
          type="text"
          inputMode="numeric"
          enterKeyHint="done"
          autoComplete="off"
          spellCheck={false}
          placeholder="10.000.000"
          value={text}
          onChange={onChange}
          onPaste={onPaste}
          onKeyDown={onKeyDown}
          aria-invalid={blocking ? true : undefined}
          aria-describedby={describedBy}
          className="tabular w-full max-w-xs rounded-md border border-line bg-surface px-3 py-2 text-base text-price placeholder:text-muted pointer-coarse:min-h-11"
        />
        {words ? (
          <span className="tabular text-sm text-muted" aria-hidden="true">
            = {words}
          </span>
        ) : null}
      </div>
      <p id={hintId} className="mt-1 text-xs text-muted" aria-live="polite">
        {notice ?? HINT}
      </p>
      {error ? (
        <p
          id={errorId}
          role={blocking ? "alert" : "status"}
          className={`mt-1 text-sm ${blocking ? "text-down" : "text-muted"}`}
        >
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
        <li>
          Cách tính: lấy số tiền nhân với mức thay đổi dự báo cho {view.h} phiên tới, ở mép dưới, mức giữa và mép trên của khoảng 80%.{" "}
          <GuideLink anchor={GUIDE_ANCHORS.vnd} topic="cách quy đổi ra số tiền" />
        </li>
        <li>{AMOUNT_NOTE}</li>
      </ul>
    </section>
  );
}
