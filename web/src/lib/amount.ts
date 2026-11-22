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

// ---------- Ô nhập số tiền: hiện dấu chấm phân cách nghìn ngay khi gõ ----------

/** Tối đa 12 chữ số (đủ cho MAX_AMOUNT_VND = 100 tỷ); gõ thêm thì bỏ qua. */
export const MAX_AMOUNT_DIGITS = 12;

/** Ký tự được coi là dấu nhóm nghìn khi gõ hoặc dán: chấm, phẩy, khoảng trắng (kể cả NBSP của vi-VN). */
const SEPARATOR = /[.,\s\u00a0\u202f]/;
const SEPARATORS = /[.,\s\u00a0\u202f]/g;

/** "900000000" → "900.000.000" (dấu chấm kiểu vi-VN). Chuỗi vào chỉ gồm chữ số. */
export function groupDigits(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

/** Số chữ số đứng trước vị trí `position` trong chuỗi đã định dạng. */
export function digitsBefore(text: string, position: number): number {
  let count = 0;
  for (let i = 0; i < Math.min(position, text.length); i += 1) if (/\d/.test(text[i])) count += 1;
  return count;
}

/** Vị trí con trỏ trong chuỗi đã định dạng, ngay sau chữ số thứ `digitCount` (0 = đầu chuỗi). */
export function caretAfterDigits(formatted: string, digitCount: number): number {
  if (digitCount <= 0) return 0;
  let seen = 0;
  for (let i = 0; i < formatted.length; i += 1) {
    if (/\d/.test(formatted[i])) {
      seen += 1;
      if (seen === digitCount) return i + 1;
    }
  }
  return formatted.length;
}

export type AmountEditReject = "not_digit" | "too_long" | "decimal";

export type AmountEdit =
  | { ok: true; digits: string; caretDigits: number }
  | { ok: false; reason: AmountEditReject };

/** Bỏ số 0 ở đầu; con trỏ lùi theo số chữ số bị bỏ ở trước nó. */
function trimLeadingZeros(digits: string, caretDigits: number): { digits: string; caretDigits: number } {
  const zeros = /^0+/.exec(digits)?.[0].length ?? 0;
  return { digits: digits.slice(zeros), caretDigits: Math.max(0, caretDigits - Math.min(zeros, caretDigits)) };
}

function finish(digits: string, caretDigits: number): AmountEdit {
  const trimmed = trimLeadingZeros(digits, caretDigits);
  if (trimmed.digits.length > MAX_AMOUNT_DIGITS) return { ok: false, reason: "too_long" };
  return { ok: true, ...trimmed };
}

/**
 * Nội dung ô sau một lần gõ/xóa (sự kiện change): chỉ nhận chữ số, dấu nhóm nghìn bỏ đi rồi thêm lại.
 * `caret` là vị trí con trỏ trong chuỗi thô; kết quả trả số chữ số đứng trước con trỏ để đặt lại.
 */
export function editFromTyping(raw: string, caret: number): AmountEdit {
  for (const char of raw) if (!/\d/.test(char) && !SEPARATOR.test(char)) return { ok: false, reason: "not_digit" };
  return finish(raw.replace(SEPARATORS, ""), digitsBefore(raw, caret));
}

/** Đuôi tiền tệ hay dính khi chép số tiền từ nơi khác: "900.000.000 đ", "900.000.000 VND". */
const CURRENCY_SUFFIX = /\s*(đồng|đ|₫|vnđ|vnd)\.?$/i;

/**
 * Số dán vào: nhận "900.000.000", "900,000,000", "900 000 000", "900000000" (có thể kèm "đ"/"VND").
 * Dấu ở chỗ không phải nhóm nghìn ("1,5", "1.234,56") là số thập phân → từ chối thay vì đoán.
 */
export function readPastedDigits(text: string): { ok: true; digits: string } | { ok: false; reason: AmountEditReject } {
  const trimmed = text.trim().replace(CURRENCY_SUFFIX, "");
  if (/^\d+$/.test(trimmed) || /^\d{1,3}([.,\s\u00a0\u202f]\d{3})+$/.test(trimmed)) {
    return { ok: true, digits: trimmed.replace(SEPARATORS, "") };
  }
  if (/^[\d.,\s\u00a0\u202f]+$/.test(trimmed) && /\d/.test(trimmed)) return { ok: false, reason: "decimal" };
  return { ok: false, reason: "not_digit" };
}

/** Dán `pasted` thay cho đoạn đang chọn [selStart, selEnd) của chuỗi đã định dạng `formatted`. */
export function editFromPaste(formatted: string, selStart: number, selEnd: number, pasted: string): AmountEdit {
  const read = readPastedDigits(pasted);
  if (!read.ok) return read;
  const digits = formatted.replace(SEPARATORS, "");
  const before = digits.slice(0, digitsBefore(formatted, selStart));
  const after = digits.slice(digitsBefore(formatted, selEnd));
  return finish(before + read.digits + after, before.length + read.digits.length);
}

/** Đọc nhanh số tiền lớn: 900.000.000 → "900 triệu đồng", 1.250.000.000 → "1,25 tỷ đồng". */
export function amountInWords(value: number): string | null {
  const say = (size: number, word: string) => {
    const rounded = Math.round((value / size) * 100) / 100;
    const text = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 2 }).format(rounded);
    // Đúng tới 2 chữ số thập phân của đơn vị thì không cần "khoảng"
    return `${value % (size / 100) === 0 ? "" : "khoảng "}${text} ${word} đồng`;
  };
  // 999.999.999 làm tròn thành "1.000 triệu": đọc theo tỷ cho tự nhiên
  if (value >= 1_000_000_000 || Math.round((value / 1_000_000) * 100) / 100 >= 1000) {
    return say(1_000_000_000, "tỷ");
  }
  if (value >= 1_000_000) return say(1_000_000, "triệu");
  return null;
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
