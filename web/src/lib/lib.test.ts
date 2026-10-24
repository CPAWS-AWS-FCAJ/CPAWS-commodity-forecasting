import { QUANTILE_LEVELS } from "../api/types";
import { sampleDetail, sampleHistory, sampleList } from "../api/sample";
import { ASSET_IDS } from "../api/types";
import { formatDate, formatNumber, formatPrice, formatProbability, formatReturnPercent } from "./format";
import {
  describeProbability,
  edgeFromReturns,
  isStaleByDate,
  modelDisplayName,
  probUpFromQuantiles,
  weekdaysSince,
} from "./forecast";
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
    expect(formatReturnPercent(0.003)).toBe("+0,30%");
    expect(formatReturnPercent(-0.021)).toBe("−2,10%");
  });

  it("định dạng ngày không lệch múi giờ", () => {
    expect(formatDate("2026-10-20")).toBe("20/10/2026");
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

  it("0 ngoài [q10, q90] → ghi 'trên 90%' / 'dưới 10%'", () => {
    const up = edgeFromReturns(levels, [0.001, 0.002, 0.003, 0.004, 0.005, 0.006, 0.007]);
    expect(up).toEqual({ zeroBelowQ10: true, zeroAboveQ90: false });
    expect(describeProbability(0.95, up).headline).toBe("Khả năng tăng trên 90%");
    expect(describeProbability(0.95, up).probUpLabel).toBe("trên 90%");

    const down = edgeFromReturns(levels, [-0.007, -0.006, -0.005, -0.004, -0.003, -0.002, -0.001]);
    expect(describeProbability(0.05, down).headline).toBe("Khả năng giảm trên 90%");
    expect(describeProbability(0.05, down).probUpLabel).toBe("dưới 10%");
  });

  it("xác suất thường: tăng, giảm, ngang nhau", () => {
    const none = { zeroBelowQ10: false, zeroAboveQ90: false };
    expect(describeProbability(0.56, none).headline).toBe("Khả năng tăng 56%");
    expect(describeProbability(0.44, none).headline).toBe("Khả năng giảm 56%");
    expect(describeProbability(0.5, none).lean).toBe("flat");
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

  it("lịch sử 91 phiên kết thúc đúng tại base_date với giá cuối khớp last_price", () => {
    const history = sampleHistory("gold");
    const detail = sampleDetail("gold");
    expect(history.points).toHaveLength(91);
    const last = history.points[history.points.length - 1];
    expect(last.date).toBe(detail.base_date);
    expect(last.price).toBeCloseTo(detail.last_price, 2);
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
