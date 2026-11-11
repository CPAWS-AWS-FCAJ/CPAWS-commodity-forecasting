/**
 * Quy đổi khoảng dự báo ra số tiền (ADR-0005, sửa ngày 04/11/2026): người xem tự nhập số tiền,
 * web tính `số tiền × exp(q)` với q là log return h phiên (q10, q50, q90) của chuỗi target.
 * Đây là giá trị giả định, giả định tỷ giá USD/VND không đổi; không dùng thêm dữ liệu giá nào.
 */

/** Khoảng số tiền nhận (đồng). Ngoài khoảng này báo lỗi thay vì tính. */
export const MIN_AMOUNT_VND = 10_000;
export const MAX_AMOUNT_VND = 100_000_000_000;

/** Câu lưu ý chép nguyên văn ADR-0005. */
export const AMOUNT_NOTE =
  "Ước tính theo dự báo, có thể sai; chưa gồm phí giao dịch, chênh lệch giá mua–bán và biến động tỷ giá USD/VND; không phải lời khuyên đầu tư.";

export type AmountParse =
  | { ok: true; value: number }
  | { ok: false; reason: "empty" | "invalid" | "too_small" | "too_large" };

/**
 * Đọc số tiền người xem gõ: chỉ nhận số nguyên đồng, cho phép dấu chấm, dấu phẩy hoặc khoảng trắng
 * làm dấu nhóm nghìn ("10.000.000", "10,000,000", "10 000 000"). Không nhận số thập phân hay số âm.
 */
export function parseAmountInput(text: string): AmountParse {
  const trimmed = text.trim();
  if (trimmed === "") return { ok: false, reason: "empty" };
  // Nhóm nghìn phải đủ 3 chữ số để "1.5" (thập phân) không bị đọc thành 15
  if (!/^\d{1,3}([.,\s]\d{3})*$|^\d+$/.test(trimmed)) return { ok: false, reason: "invalid" };
  const value = Number(trimmed.replace(/[.,\s]/g, ""));
  if (!Number.isSafeInteger(value)) return { ok: false, reason: "too_large" };
  if (value < MIN_AMOUNT_VND) return { ok: false, reason: "too_small" };
  if (value > MAX_AMOUNT_VND) return { ok: false, reason: "too_large" };
  return { ok: true, value };
}

/** Giá trị giả định của số tiền nếu giá thay đổi đúng bằng log return q: số tiền × e^q. */
export function hypotheticalAmount(amount: number, logReturn: number): number {
  return amount * Math.exp(logReturn);
}

/** Làm tròn đến nghìn đồng như các số VND khác trên web (skill forecast-display). */
export function roundToThousand(value: number): number {
  return Math.round(value / 1000) * 1000;
}

export interface AmountRange {
  low: number;
  mid: number;
  high: number;
}

/** Số tiền giả định tại q10, q50, q90, đã làm tròn nghìn đồng. */
export function amountRange(amount: number, low: number, mid: number, high: number): AmountRange {
  return {
    low: roundToThousand(hypotheticalAmount(amount, low)),
    mid: roundToThousand(hypotheticalAmount(amount, mid)),
    high: roundToThousand(hypotheticalAmount(amount, high)),
  };
}
