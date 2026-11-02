// Khối "Độ tin cậy" (rolling_8w) theo skill forecast-display và contract GET /accuracy/{asset}.
// Chỉ đọc display_value/display_status và các trường đếm; không dùng `value` nội bộ.
import {
  ACCURACY_DATA_STATUSES,
  HORIZON_DISPLAY_STATUS,
  OVERALL_DISPLAY_STATUSES,
} from "../api/types";
import type {
  AccuracyDataStatus,
  AccuracyResponse,
  CoverageMetric,
  ValueMetric,
} from "../api/types";
import { formatNumber } from "./format";
import { roundPercent } from "./forecast";

const METRIC_KEYS = ["coverage_80", "width_80", "width_80_pct", "sign_accuracy", "up_rate"] as const;

/** Response có trạng thái ngoài enum đóng của contract: báo lỗi, không đoán. */
export class AccuracyFormatError extends Error {
  constructor(detail: string) {
    super(`Dữ liệu độ tin cậy không đúng định dạng (${detail}).`);
    this.name = "AccuracyFormatError";
  }
}

function oneOf(values: readonly string[], value: unknown): boolean {
  return typeof value === "string" && values.includes(value);
}

export function assertAccuracyStatuses(response: AccuracyResponse): void {
  if (!oneOf(ACCURACY_DATA_STATUSES, response.data_status)) {
    throw new AccuracyFormatError(`data_status = ${String(response.data_status)}`);
  }
  for (const key of METRIC_KEYS) {
    const status = response.overall?.[key]?.display_status;
    if (!oneOf(OVERALL_DISPLAY_STATUSES, status)) {
      throw new AccuracyFormatError(`overall.${key}.display_status = ${String(status)}`);
    }
  }
  if (typeof response.overall.coverage_80.min_display_base_dates !== "number") {
    throw new AccuracyFormatError("thiếu overall.coverage_80.min_display_base_dates");
  }
  if (!Array.isArray(response.by_horizon)) throw new AccuracyFormatError("thiếu by_horizon");
  for (const horizon of response.by_horizon) {
    for (const key of METRIC_KEYS) {
      const status = horizon[key]?.display_status;
      if (status !== HORIZON_DISPLAY_STATUS) {
        throw new AccuracyFormatError(`by_horizon h=${horizon.h} ${key}.display_status = ${String(status)}`);
      }
    }
  }
}

function readyValue(metric: ValueMetric | CoverageMetric): number | null {
  return metric.display_status === "ready" ? metric.display_value : null;
}

/** "73% (127/175 cặp)"; null khi không được hiện số. */
export function formatCoverage(metric: CoverageMetric): string | null {
  const value = readyValue(metric);
  if (value === null) return null;
  return `${roundPercent(value)}% (${metric.covered_count}/${metric.n_obs} cặp)`;
}

/** width_80_pct.display_value đã là % giá (4.2 nghĩa là 4,2%): chỉ làm tròn 1 chữ số. */
export function formatWidthPct(metric: ValueMetric): string | null {
  const value = readyValue(metric);
  return value === null ? null : `${formatNumber(value, 1)}%`;
}

/** sign_accuracy và up_rate luôn đi cùng nhau: thiếu một trong hai thì không hiện cả cặp. */
export function formatSignPair(
  sign: ValueMetric,
  upRate: ValueMetric,
): { sign: string; upRate: string } | null {
  const signValue = readyValue(sign);
  const upValue = readyValue(upRate);
  if (signValue === null || upValue === null) return null;
  return { sign: `${roundPercent(signValue)}%`, upRate: `${roundPercent(upValue)}%` };
}

/** Theo từng h chỉ hiện X/Y; null khi n_obs = 0 (giao diện hiện "—"). */
export function formatHorizonCount(metric: CoverageMetric): string | null {
  return metric.n_obs > 0 ? `${metric.covered_count}/${metric.n_obs}` : null;
}

export type ReliabilityState =
  | { kind: "not_ready" }
  | { kind: "collecting"; baseDates: number; minBaseDates: number }
  | {
      kind: "ready";
      coverage: string | null;
      widthPct: string | null;
      signPair: { sign: string; upRate: string } | null;
    };

/** Gọi sau assertAccuracyStatuses. */
export function reliabilityState(response: AccuracyResponse): ReliabilityState {
  const status = response.data_status as AccuracyDataStatus;
  const { overall } = response;
  if (status === "not_ready") return { kind: "not_ready" };
  if (status === "collecting") {
    return {
      kind: "collecting",
      baseDates: overall.coverage_80.n_base_dates,
      minBaseDates: overall.coverage_80.min_display_base_dates,
    };
  }
  return {
    kind: "ready",
    coverage: formatCoverage(overall.coverage_80),
    widthPct: formatWidthPct(overall.width_80_pct),
    signPair: formatSignPair(overall.sign_accuracy, overall.up_rate),
  };
}
