import type { ClosePoint } from "../api/types";
import {
  FORECAST_CHART_RANGES,
  OVERVIEW_RANGES,
  changeBetween,
  defaultRange,
  isRangeAvailable,
  rangeUnavailableReason,
  formatChangeMagnitude,
  formatChangePercent,
  lastSessionChange,
  rangeStats,
  sliceRange,
} from "./priceOverview";

const points: ClosePoint[] = Array.from({ length: 30 }, (_, i) => ({
  base_date: `2026-10-${String(i + 1).padStart(2, "0")}`,
  last_price: 100 + i,
}));

describe("priceOverview", () => {
  it("mốc: 7 phiên, 1 tháng (21), 6 tháng (126), 1 năm (252), 2 năm (504); trang sản phẩm bỏ 7 phiên", () => {
    expect(OVERVIEW_RANGES.map((range) => [range.label, range.sessions])).toEqual([
      ["7 phiên", 7],
      ["1 tháng", 21],
      ["6 tháng", 126],
      ["1 năm", 252],
      ["2 năm", 504],
    ]);
    expect(FORECAST_CHART_RANGES.map((range) => range.sessions)).toEqual([21, 126, 252, 504]);
  });

  it("N phiên lấy N + 1 điểm cuối; null (chưa mốc nào đủ) lấy hết", () => {
    expect(sliceRange(points, OVERVIEW_RANGES[0])).toHaveLength(8);
    expect(sliceRange(points, OVERVIEW_RANGES[1])).toHaveLength(22);
    expect(sliceRange(points, null)).toHaveLength(30);
  });

  it("mốc vượt số điểm đang có thì tắt, có lý do", () => {
    const oneMonth = OVERVIEW_RANGES[1];
    expect(isRangeAvailable(oneMonth, 22)).toBe(true);
    expect(isRangeAvailable(oneMonth, 21)).toBe(false);
    expect(rangeUnavailableReason(oneMonth, 15)).toBe("Mốc 1 tháng cần 22 giá cuối phiên, hiện mới có 15.");
  });

  it("mặc định: mốc lớn nhất đủ dữ liệu nhưng không quá giới hạn; không mốc nào đủ → null", () => {
    expect(defaultRange(FORECAST_CHART_RANGES, 520, 126)?.label).toBe("6 tháng");
    expect(defaultRange(FORECAST_CHART_RANGES, 100, 126)?.label).toBe("1 tháng");
    expect(defaultRange(FORECAST_CHART_RANGES, 20, 126)).toBeNull();
    expect(defaultRange(OVERVIEW_RANGES, 520, 21)?.label).toBe("1 tháng");
    expect(defaultRange(OVERVIEW_RANGES, 15, 21)?.label).toBe("7 phiên");
  });

  it("thay đổi so với phiên trước tính theo cuối / đầu − 1", () => {
    const change = lastSessionChange([
      { base_date: "2026-11-18", last_price: 80 },
      { base_date: "2026-11-19", last_price: 82 },
    ]);
    expect(change?.direction).toBe("up");
    expect(change?.ratio).toBeCloseTo(0.025);
    expect(change?.delta).toBeCloseTo(2);
    expect(change?.fromDate).toBe("2026-11-18");
  });

  it("chưa đủ 2 điểm thì không có thay đổi", () => {
    expect(lastSessionChange([points[0]])).toBeNull();
    expect(lastSessionChange([])).toBeNull();
  });

  it("thay đổi làm tròn về 0,0% là không đổi, giá không dương thì bỏ", () => {
    const flat = changeBetween(
      { base_date: "a", last_price: 100 },
      { base_date: "b", last_price: 100.04 },
    );
    expect(flat?.direction).toBe("flat");
    expect(changeBetween({ base_date: "a", last_price: 0 }, { base_date: "b", last_price: 1 })).toBeNull();
  });

  it("cao nhất, thấp nhất và thay đổi của khoảng", () => {
    const stats = rangeStats(points.slice(-8));
    expect(stats?.high).toBe(129);
    expect(stats?.low).toBe(122);
    expect(stats?.change?.direction).toBe("up");
    expect(rangeStats([])).toBeNull();
  });

  it("định dạng phần trăm theo vi-VN, 1 chữ số", () => {
    expect(formatChangePercent(0.0123)).toBe("+1,2%");
    expect(formatChangePercent(-0.0087)).toBe("−0,9%");
    expect(formatChangePercent(0.0002)).toBe("0,0%");
    expect(formatChangeMagnitude(-0.0331)).toBe("3,3%");
  });
});
