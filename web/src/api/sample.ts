// DỮ LIỆU MẪU cho web khi API chưa sẵn sàng. Không phải dự báo thật.
// Mọi bản ghi đều có is_sample = true và model_version = "sample"; giao diện phải hiện nhãn "dữ liệu mẫu".
// Bản ghi tuân thủ contract: 7 phân vị không giảm, prob_up nội suy và kẹp trong [0.05, 0.95].

import { ApiError } from "./client";
import { ASSET_IDS, QUANTILE_LEVELS } from "./types";
import type {
  AssetId,
  ForecastDetail,
  ForecastListResponse,
  ForecastSummary,
  HistoryResponse,
  HorizonDetail,
  PriceUnit,
} from "./types";
import type { AccuracyResponse } from "./types";
import type { SampleAccuracy } from "./config";
import { probUpFromQuantiles } from "../lib/forecast";
// Fixtures Accuracy của contract (PR #62), đều synthetic: dùng chung một nguồn với test backend.
import accuracyNotReady from "../../../tests/fixtures/accuracy/not_ready.json";
import accuracyCollecting from "../../../tests/fixtures/accuracy/collecting.json";
import accuracyReady from "../../../tests/fixtures/accuracy/ready.json";

const DISCLAIMER = "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư.";
const BASE_DATE = "2026-10-20"; // thứ Ba
const CREATED_AT = "2026-10-20T12:40:05Z";
const FX = { usd_vnd: 26310, date: BASE_DATE };
const HISTORY_SESSIONS = 91; // 90 phiên + phiên cuối

// z của chuẩn tắc ứng với 7 mức phân vị trong QUANTILE_LEVELS
const Z = [-1.6449, -1.2816, -0.6745, 0, 0.6745, 1.2816, 1.6449];

interface SampleSpec {
  targetSeries: string;
  unit: PriceUnit;
  lastPrice: number;
  dailySigma: number;
  dailyDrift: number;
  roll: boolean;
  seed: number;
}

const SPECS: Record<AssetId, SampleSpec> = {
  gold: { targetSeries: "GLD", unit: "USD/oz", lastPrice: 2655.4, dailySigma: 0.0085, dailyDrift: 0.0003, roll: false, seed: 11 },
  silver: { targetSeries: "SLV", unit: "USD/oz", lastPrice: 31.24, dailySigma: 0.017, dailyDrift: 0.0004, roll: false, seed: 23 },
  brent: { targetSeries: "BZ=F", unit: "USD/bbl", lastPrice: 74.86, dailySigma: 0.016, dailyDrift: -0.0002, roll: false, seed: 37 },
  wti: { targetSeries: "CL=F", unit: "USD/bbl", lastPrice: 71.32, dailySigma: 0.017, dailyDrift: 0.0001, roll: true, seed: 41 },
};

function round(value: number, digits: number): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

/** PRNG có seed (mulberry32) để dữ liệu mẫu giống nhau giữa các lần tải. */
function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian(random: () => number): number {
  const u = Math.max(random(), 1e-12);
  const v = random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function addDays(iso: string, days: number): string {
  return new Date(new Date(`${iso}T00:00:00Z`).getTime() + days * 86_400_000)
    .toISOString()
    .slice(0, 10);
}

function isWeekday(iso: string): boolean {
  const day = new Date(`${iso}T00:00:00Z`).getUTCDay();
  return day !== 0 && day !== 6;
}

/** Ngày làm việc thứ n sau `from` (n >= 1). Mẫu không xét ngày lễ. */
function nextWeekdays(from: string, count: number): string[] {
  const result: string[] = [];
  let cursor = from;
  while (result.length < count) {
    cursor = addDays(cursor, 1);
    if (isWeekday(cursor)) result.push(cursor);
  }
  return result;
}

function previousWeekdays(from: string, count: number): string[] {
  const result: string[] = [];
  let cursor = from;
  while (result.length < count) {
    cursor = addDays(cursor, -1);
    if (isWeekday(cursor)) result.push(cursor);
  }
  return result.reverse();
}

function buildHorizons(spec: SampleSpec): HorizonDetail[] {
  const dates = nextWeekdays(BASE_DATE, 7);
  return dates.map((targetDate, index) => {
    const h = index + 1;
    const returns = Z.map((z) => round(spec.dailyDrift * h + z * spec.dailySigma * Math.sqrt(h), 6));
    const prices = returns.map((r) => round(spec.lastPrice * Math.exp(r), 2));
    return {
      h,
      target_date: targetDate,
      returns,
      prices,
      prob_up: round(probUpFromQuantiles(QUANTILE_LEVELS, returns), 2),
    };
  });
}

export function sampleDetail(asset: AssetId): ForecastDetail {
  const spec = SPECS[asset];
  if (!spec) throw new ApiError(400, "invalid_asset", "Mã tài sản không hợp lệ.");
  return {
    asset,
    target_series: spec.targetSeries,
    base_date: BASE_DATE,
    created_at: CREATED_AT,
    model_version: "sample",
    last_price: spec.lastPrice,
    price_unit: spec.unit,
    quantile_levels: [...QUANTILE_LEVELS],
    horizons: buildHorizons(spec),
    fx: FX,
    stale_sources: [],
    roll_in_horizon: spec.roll,
    is_sample: true,
    disclaimer: DISCLAIMER,
  };
}

export function sampleList(): ForecastListResponse {
  const items: ForecastSummary[] = ASSET_IDS.map((asset) => {
    const detail = sampleDetail(asset);
    const pick = (h: number) => {
      const horizon = detail.horizons[h - 1];
      return {
        target_date: horizon.target_date,
        p10: horizon.prices[1],
        p50: horizon.prices[3],
        p90: horizon.prices[5],
        prob_up: horizon.prob_up,
      };
    };
    return {
      asset,
      target_series: detail.target_series,
      base_date: detail.base_date,
      last_price: detail.last_price,
      price_unit: detail.price_unit,
      h1: pick(1),
      h7: pick(7),
      stale: detail.stale_sources.length > 0,
      roll_in_horizon: detail.roll_in_horizon,
      is_sample: true,
    };
  });
  return { items, disclaimer: DISCLAIMER };
}

const ACCURACY_FIXTURES: Record<SampleAccuracy, unknown> = {
  not_ready: accuracyNotReady,
  collecting: accuracyCollecting,
  ready: accuracyReady,
};

/** Fixture GET /accuracy (viết cho gold); đổi `asset` để dùng cho cả 4 tài sản. */
export function sampleAccuracy(asset: AssetId, which: SampleAccuracy): AccuracyResponse {
  if (!SPECS[asset]) throw new ApiError(400, "invalid_asset", "Mã tài sản không hợp lệ.");
  return { ...(ACCURACY_FIXTURES[which] as AccuracyResponse), asset };
}

/** Bước ngẫu nhiên lùi từ giá cuối, 91 phiên kết thúc đúng tại BASE_DATE. */
export function sampleHistory(asset: AssetId): HistoryResponse {
  const spec = SPECS[asset];
  if (!spec) throw new ApiError(400, "invalid_asset", "Mã tài sản không hợp lệ.");
  const random = mulberry32(spec.seed);
  const dates = [...previousWeekdays(BASE_DATE, HISTORY_SESSIONS - 1), BASE_DATE];
  const prices = new Array<number>(dates.length);
  prices[dates.length - 1] = spec.lastPrice;
  for (let i = dates.length - 1; i > 0; i -= 1) {
    const step = spec.dailyDrift + spec.dailySigma * gaussian(random);
    prices[i - 1] = prices[i] / Math.exp(step);
  }
  return {
    asset,
    price_unit: spec.unit,
    points: dates.map((date, i) => ({ date, price: round(prices[i], 2) })),
  };
}
