import { QUANTILE_LEVELS } from "../api/types";
import { SAMPLE_HISTORY_POINTS, sampleCloses, sampleDetail, sampleDetailWithHistory, sampleList } from "../api/sample";
import { ASSET_IDS } from "../api/types";
import { buildFanData, describeMedianChange, jointIndex } from "./chartData";
import {
  dateTickFormatter,
  formatAxisPrice,
  formatDate,
  formatDateVn,
  formatDayMonth,
  formatMonthYear,
  formatNumber,
  monthStartTicks,
  formatPrice,
  formatProbability,
  formatReturnPercent,
} from "./format";
import {
  describeProbability,
  isStaleByDate,
  modelDisplayName,
  probUpFromQuantiles,
  roundPercent,
  weekdaysSince,
} from "./forecast";
import {
  MAX_AMOUNT_DIGITS,
  MIN_AMOUNT_VND,
  amountInWords,
  amountRange,
  caretAfterDigits,
  digitsBefore,
  editFromPaste,
  editFromTyping,
  groupDigits,
  hypotheticalAmount,
  parseAmountInput,
  readPastedDigits,
  roundToThousand,
} from "./amount";
import { isPriceHidden } from "./assets";
import { LUONG_GRAMS, TROY_OUNCE_GRAMS, usdToVnd } from "./units";

describe("units", () => {
  it("quy đổi USD/oz sang VND/lượng cho vàng", () => {
    const vnd = usdToVnd("gold", 2000, 26000);
    expect(vnd).toBeCloseTo(((2000 * LUONG_GRAMS) / TROY_OUNCE_GRAMS) * 26000, 2);
    // ~62,7 triệu đồng/lượng
    expect(vnd).toBeGreaterThan(62_000_000);
    expect(vnd).toBeLessThan(63_500_000);
  });

  it("dầu chỉ nhân tỷ giá (VND/thùng)", () => {
    expect(usdToVnd("wti", 70, 26000)).toBe(1_820_000);
  });
});

describe("format", () => {
  it("định dạng số theo vi-VN", () => {
    expect(formatNumber(1958)).toBe("1.958");
    expect(formatNumber(71.5, 2)).toBe("71,50");
  });

  it("làm tròn giá: vàng 1 USD, bạc/dầu 2 chữ số, VND đến nghìn đồng", () => {
    expect(formatPrice("gold", 2655.4, "USD")).toBe("2.655");
    expect(formatPrice("silver", 31.236, "USD")).toBe("31,24");
    expect(formatPrice("gold", 84_215_499, "VND")).toBe("84.215.000");
  });

  it("xác suất làm tròn 1%, return có dấu", () => {
    expect(formatProbability(0.5649)).toBe("56%");
    expect(formatReturnPercent(0.003)).toBe("+0,3%");
    expect(formatReturnPercent(-0.021)).toBe("−2,1%");
    expect(formatReturnPercent(0.003, 2)).toBe("+0,30%");
  });

  it("% thay đổi làm tròn về 0 thì không ghi dấu", () => {
    expect(formatReturnPercent(0.0004)).toBe("0,0%");
    expect(formatReturnPercent(-0.0004)).toBe("0,0%");
    expect(formatReturnPercent(0.0004, 2)).toBe("+0,04%");
  });

  it("định dạng ngày không lệch múi giờ", () => {
    expect(formatDate("2026-10-20")).toBe("20/10/2026");
    // ngày theo giờ Việt Nam: tin Fed 18:00 UTC sang VN đã là ngày hôm sau
    expect(formatDateVn("2026-10-28T18:00:00Z")).toBe("29/10/2026");
    expect(formatDateVn("2026-10-28T10:00:00Z")).toBe("28/10/2026");
  });
});

describe("probability", () => {
  const levels = QUANTILE_LEVELS;

  it("nội suy xác suất tăng từ phân vị", () => {
    const returns = [-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03];
    expect(probUpFromQuantiles(levels, returns)).toBeCloseTo(0.5, 6);
  });

  it("kẹp trong [0.05, 0.95]", () => {
    expect(probUpFromQuantiles(levels, [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07])).toBe(0.95);
    expect(probUpFromQuantiles(levels, [-0.07, -0.06, -0.05, -0.04, -0.03, -0.02, -0.01])).toBe(0.05);
  });

  it("nhãn hướng so trên xác suất đã làm tròn 1% (ngưỡng 60/40)", () => {
    expect(describeProbability(0.597)).toMatchObject({ lean: "up", label: "Nghiêng tăng", probUpLabel: "60%" });
    expect(describeProbability(0.404)).toMatchObject({ lean: "down", label: "Nghiêng giảm", probUpLabel: "40%" });
    expect(describeProbability(0.55)).toMatchObject({ lean: "flat", label: "Chưa rõ xu hướng", probUpLabel: "55%" });
    expect(describeProbability(0.594).label).toBe("Chưa rõ xu hướng");
    expect(describeProbability(0.406).label).toBe("Chưa rõ xu hướng");
    expect(describeProbability(0.6).label).toBe("Nghiêng tăng");
    expect(describeProbability(0.4).label).toBe("Nghiêng giảm");
  });

  it("chỉ đúng biên kẹp mới ghi '≥ 95%' / '≤ 5%'; 0,945 vẫn là 95%", () => {
    expect(describeProbability(0.95).probUpLabel).toBe("≥ 95%");
    expect(describeProbability(0.05).probUpLabel).toBe("≤ 5%");
    expect(describeProbability(0.945).probUpLabel).toBe("95%");
    expect(describeProbability(0.055).probUpLabel).toBe("6%");
  });

  it("làm tròn % khử sai số dấu phẩy động", () => {
    expect(roundPercent(0.585)).toBe(59);
    expect(roundPercent(0.725714)).toBe(73);
  });
});

describe("stale", () => {
  it("đếm ngày làm việc sau base_date", () => {
    // Thứ Sáu 2026-10-16 → thứ Ba 2026-10-20: T2, T3 = 2
    expect(weekdaysSince("2026-10-16", "2026-10-20")).toBe(2);
    expect(weekdaysSince("2026-10-20", "2026-10-20")).toBe(0);
  });

  it("chậm hơn 2 ngày làm việc là cũ; dữ liệu mẫu không bao giờ cũ", () => {
    expect(isStaleByDate("2026-10-14", "2026-10-21", false)).toBe(true);
    expect(isStaleByDate("2026-10-19", "2026-10-21", false)).toBe(false);
    expect(isStaleByDate("2026-01-01", "2026-10-21", true)).toBe(false);
  });
});

describe("dữ liệu mẫu tuân thủ contract", () => {
  it.each(ASSET_IDS)("%s: 7 phân vị không giảm, 7 mức h, prob_up trong [0.05, 0.95]", (asset) => {
    const detail = sampleDetail(asset);
    expect(detail.is_sample).toBe(true);
    expect(detail.model_version).toBe("sample");
    expect(detail.quantile_levels).toEqual([0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95]);
    expect(detail.horizons.map((h) => h.h)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    for (const horizon of detail.horizons) {
      expect(horizon.returns).toHaveLength(7);
      expect(horizon.prices).toHaveLength(7);
      for (let i = 1; i < 7; i += 1) {
        expect(horizon.returns[i]).toBeGreaterThanOrEqual(horizon.returns[i - 1]);
        expect(horizon.prices[i]).toBeGreaterThanOrEqual(horizon.prices[i - 1]);
      }
      expect(horizon.prob_up).toBeGreaterThanOrEqual(0.05);
      expect(horizon.prob_up).toBeLessThanOrEqual(0.95);
    }
  });

  it("danh sách tóm tắt có đủ 4 tài sản, p10 <= p50 <= p90", () => {
    const list = sampleList();
    expect(list.items.map((i) => i.asset)).toEqual([...ASSET_IDS]);
    for (const item of list.items) {
      expect(item.h7.p10).toBeLessThanOrEqual(item.h7.p50);
      expect(item.h7.p50).toBeLessThanOrEqual(item.h7.p90);
    }
  });

  it("lịch sử ~520 phiên, cũ → mới, kết thúc đúng tại base_date với giá cuối khớp last_price", () => {
    const closes = sampleCloses("gold");
    const detail = sampleDetail("gold");
    expect(closes).toHaveLength(SAMPLE_HISTORY_POINTS);
    expect(SAMPLE_HISTORY_POINTS).toBeGreaterThanOrEqual(505); // đủ cho mốc 2 năm (504 phiên)
    const last = closes[closes.length - 1];
    expect(last.base_date).toBe(detail.base_date);
    expect(last.last_price).toBeCloseTo(detail.last_price, 2);
    for (let i = 1; i < closes.length; i += 1) {
      expect(closes[i].base_date > closes[i - 1].base_date).toBe(true);
      expect(closes[i].last_price).toBeGreaterThan(0);
    }
  });

  it("price_history mẫu cắt đúng N điểm gần nhất; N ngoài 1–520 báo invalid_history như API", () => {
    expect(sampleDetailWithHistory("wti", 21).price_history).toHaveLength(21);
    expect(sampleDetailWithHistory("wti", 520).price_history).toHaveLength(520);
    expect(() => sampleDetailWithHistory("wti", 0)).toThrow(/history/);
    expect(() => sampleDetailWithHistory("wti", 521)).toThrow(/history/);
  });
});

describe("isPriceHidden", () => {
  it("chỉ ẩn vàng và bạc khi tắt cờ hiển thị giá kim loại", () => {
    expect(isPriceHidden("gold", false)).toBe(true);
    expect(isPriceHidden("silver", false)).toBe(true);
    expect(isPriceHidden("brent", false)).toBe(false);
    expect(isPriceHidden("wti", false)).toBe(false);
  });

  it("không ẩn gì khi bật cờ", () => {
    for (const asset of ASSET_IDS) expect(isPriceHidden(asset, true)).toBe(false);
  });
});

describe("modelDisplayName", () => {
  it("đặt tên dễ hiểu cho mốc thống kê 252 phiên", () => {
    expect(modelDisplayName("baseline-q252")).toBe("Mốc thống kê 252 phiên");
  });

  it("trả null cho mô hình khác hoặc khi thiếu model_version", () => {
    expect(modelDisplayName("dlinear-41e13dc5de3d")).toBeNull();
    expect(modelDisplayName("sample")).toBeNull();
    expect(modelDisplayName(undefined)).toBeNull();
  });
});

describe("amount (ADR-0005 mục (2))", () => {
  it("ví dụ trong ADR: 10.000.000 đồng, q10 −0,025, q90 +0,031 → 9,75–10,31 triệu", () => {
    const range = amountRange(10_000_000, -0.025, 0, 0.031);
    expect(range).toEqual({ low: 9_753_000, mid: 10_000_000, high: 10_315_000 });
    expect(hypotheticalAmount(10_000_000, -0.025)).toBeCloseTo(10_000_000 * Math.exp(-0.025), 6);
  });

  it("làm tròn đến nghìn đồng", () => {
    expect(roundToThousand(9_753_499)).toBe(9_753_000);
    expect(roundToThousand(9_753_500)).toBe(9_754_000);
  });

  it("đọc số tiền có dấu nhóm nghìn", () => {
    expect(parseAmountInput("10.000.000")).toEqual({ ok: true, value: 10_000_000 });
    expect(parseAmountInput("10,000,000")).toEqual({ ok: true, value: 10_000_000 });
    expect(parseAmountInput(" 10 000 000 ")).toEqual({ ok: true, value: 10_000_000 });
    expect(parseAmountInput("10000000")).toEqual({ ok: true, value: 10_000_000 });
  });

  it("từ chối ô trống, số thập phân, số âm, chữ và số ngoài khoảng", () => {
    expect(parseAmountInput("")).toEqual({ ok: false, reason: "empty" });
    expect(parseAmountInput("1.5")).toEqual({ ok: false, reason: "invalid" });
    expect(parseAmountInput("1,50")).toEqual({ ok: false, reason: "invalid" });
    expect(parseAmountInput("-1000000")).toEqual({ ok: false, reason: "invalid" });
    expect(parseAmountInput("10 triệu")).toEqual({ ok: false, reason: "invalid" });
    expect(parseAmountInput("9.999")).toEqual({ ok: false, reason: "too_small" });
    expect(parseAmountInput(String(MIN_AMOUNT_VND))).toEqual({ ok: true, value: MIN_AMOUNT_VND });
    expect(parseAmountInput("100.000.000.001")).toEqual({ ok: false, reason: "too_large" });
    expect(parseAmountInput("99999999999999999999")).toEqual({ ok: false, reason: "too_large" });
  });
});

describe("ô nhập số tiền: dấu chấm nhóm nghìn khi gõ", () => {
  it("nhóm 3 chữ số bằng dấu chấm kiểu vi-VN", () => {
    expect(groupDigits("")).toBe("");
    expect(groupDigits("900")).toBe("900");
    expect(groupDigits("9000")).toBe("9.000");
    expect(groupDigits("900000000")).toBe("900.000.000");
    expect(groupDigits("100000000000")).toBe("100.000.000.000");
  });

  it("gõ thêm chữ số ở cuối hay ở giữa: giữ số chữ số đứng trước con trỏ", () => {
    // "900.000" gõ thêm "1" ở cuối → con trỏ sau 7 chữ số
    expect(editFromTyping("900.0001", 8)).toEqual({ ok: true, digits: "9000001", caretDigits: 7 });
    expect(caretAfterDigits("9.000.001", 7)).toBe(9);
    // "1.234" gõ "5" sau chữ "1" → "15.234", con trỏ sau chữ số thứ 2
    expect(editFromTyping("15.234", 2)).toEqual({ ok: true, digits: "15234", caretDigits: 2 });
    expect(caretAfterDigits("15.234", 2)).toBe(2);
    // "12.345" xóa chữ "3" → "12.45", con trỏ sau chữ số thứ 2
    expect(editFromTyping("12.45", 3)).toEqual({ ok: true, digits: "1245", caretDigits: 2 });
    expect(caretAfterDigits("1.245", 2)).toBe(3);
  });

  it("chỉ nhận chữ số; bỏ số 0 ở đầu; giới hạn số chữ số", () => {
    expect(editFromTyping("12a", 3)).toEqual({ ok: false, reason: "not_digit" });
    expect(editFromTyping("-5", 2)).toEqual({ ok: false, reason: "not_digit" });
    expect(editFromTyping("0", 1)).toEqual({ ok: true, digits: "", caretDigits: 0 });
    expect(editFromTyping("0.012", 5)).toEqual({ ok: true, digits: "12", caretDigits: 2 });
    expect(editFromTyping("9".repeat(MAX_AMOUNT_DIGITS), MAX_AMOUNT_DIGITS).ok).toBe(true);
    expect(editFromTyping("9".repeat(MAX_AMOUNT_DIGITS + 1), MAX_AMOUNT_DIGITS + 1)).toEqual({
      ok: false,
      reason: "too_long",
    });
  });

  it("dán '900.000.000', '900000000', '900,000,000', '900 000 000 đ' đều được; số thập phân bị từ chối", () => {
    for (const text of ["900.000.000", "900000000", "900,000,000", "900 000 000", " 900.000.000 đ", "900.000.000 VND"]) {
      expect(readPastedDigits(text)).toEqual({ ok: true, digits: "900000000" });
    }
    expect(readPastedDigits("1,5")).toEqual({ ok: false, reason: "decimal" });
    expect(readPastedDigits("1.234,56")).toEqual({ ok: false, reason: "decimal" });
    expect(readPastedDigits("10 triệu")).toEqual({ ok: false, reason: "not_digit" });
    expect(readPastedDigits("")).toEqual({ ok: false, reason: "not_digit" });
  });

  it("dán thay cho đoạn đang chọn", () => {
    // ô trống
    expect(editFromPaste("", 0, 0, "900.000.000")).toEqual({ ok: true, digits: "900000000", caretDigits: 9 });
    // "1.000" chọn hết rồi dán
    expect(editFromPaste("1.000", 0, 5, "25000")).toEqual({ ok: true, digits: "25000", caretDigits: 5 });
    // "1.000" dán "5" sau chữ số đầu
    expect(editFromPaste("1.000", 1, 1, "5")).toEqual({ ok: true, digits: "15000", caretDigits: 2 });
    expect(editFromPaste("", 0, 0, "1234567890123")).toEqual({ ok: false, reason: "too_long" });
    expect(digitsBefore("1.000", 2)).toBe(1);
  });

  it("đọc nhanh số tiền lớn", () => {
    expect(amountInWords(900_000_000)).toBe("900 triệu đồng");
    expect(amountInWords(1_250_000_000)).toBe("1,25 tỷ đồng");
    expect(amountInWords(1_234_567_890)).toBe("khoảng 1,23 tỷ đồng");
    expect(amountInWords(999_999_999)).toBe("khoảng 1 tỷ đồng");
    expect(amountInWords(500_000)).toBeNull();
  });
});

describe("biểu đồ giá thực tế và dự báo", () => {
  it("nối lịch sử với 7 phiên dự báo; chỉ điểm dự báo có h và changeMid", () => {
    const detail = sampleDetailWithHistory("wti", 22);
    const data = buildFanData("wti", detail, detail.price_history, "USD");
    expect(data).toHaveLength(22 + 7);
    const joint = jointIndex(data);
    expect(joint).toBe(21);
    expect(data[joint].date).toBe(detail.base_date);
    expect(data[joint].median).toBeCloseTo(detail.last_price, 6);
    expect(data[joint].h).toBeUndefined();
    const forecast = data.slice(joint + 1);
    expect(forecast.map((point) => point.h)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    for (const point of forecast) {
      expect(point.price).toBeUndefined();
      expect(point.low!).toBeLessThanOrEqual(point.median!);
      expect(point.median!).toBeLessThanOrEqual(point.high!);
      expect(point.changeMid).toBeDefined();
    }
    expect(data.slice(0, joint).every((point) => point.median === undefined)).toBe(true);
  });

  it("không có lịch sử: vẫn vẽ phiên gần nhất + 7 phiên dự báo", () => {
    const detail = sampleDetail("brent");
    const data = buildFanData("brent", detail, undefined, "VND");
    expect(data).toHaveLength(8);
    expect(data[0].price).toBeCloseTo(detail.last_price * detail.fx.usd_vnd, 0);
  });

  it("thay đổi của trung vị có hướng và độ lớn 1 chữ số", () => {
    expect(describeMedianChange(0.0042)).toEqual({ direction: "up", magnitude: "0,4%" });
    expect(describeMedianChange(-0.0123)).toEqual({ direction: "down", magnitude: "1,2%" });
    expect(describeMedianChange(0.0004)).toEqual({ direction: "flat", magnitude: "0,0%" });
  });

  it("nhãn trục: ngày/tháng khi ngắn, tháng/năm khi dài; giá VND theo triệu", () => {
    expect(formatMonthYear("2026-10-20")).toBe("10/2026");
    expect(dateTickFormatter(30)).toBe(formatDayMonth);
    expect(dateTickFormatter(260)).toBe(formatMonthYear);
    expect(formatAxisPrice("gold", "USD")(2655.4)).toBe("2.655");
    expect(formatAxisPrice("wti", "USD")(71.32)).toBe("71,3");
    expect(formatAxisPrice("wti", "VND")(1_876_000)).toBe("1,9 tr");
  });

  it("mốc theo tháng: phiên đầu mỗi tháng, không lặp, tối đa 8 mốc", () => {
    const dates = sampleCloses("gold").map((point) => point.base_date);
    const six = monthStartTicks(dates.slice(-127));
    expect(new Set(six.map(formatMonthYear)).size).toBe(six.length);
    expect(six.every((date, i) => i === 0 || date > six[i - 1])).toBe(true);
    expect(monthStartTicks(dates).length).toBeLessThanOrEqual(8);
    expect(monthStartTicks(["2026-10-30", "2026-11-02", "2026-11-03"])).toEqual(["2026-11-02"]);
  });
});
