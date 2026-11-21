import { apiGet, ApiError } from "./client";
import { config } from "./config";
import type {
  AccuracyResponse,
  AssetId,
  ForecastDetail,
  ForecastDetailWithHistory,
  ForecastListResponse,
} from "./types";
import { isAssetId } from "./types";
import { assertAccuracyStatuses } from "../lib/accuracy";

// Dữ liệu mẫu nạp muộn: bản chạy với API thật không phải tải module này.
const loadSample = () => import("./sample");

export async function getForecasts(signal?: AbortSignal): Promise<ForecastListResponse> {
  if (config.useSample) return (await loadSample()).sampleList();
  return apiGet<ForecastListResponse>("/forecasts", signal);
}

export async function getForecast(asset: AssetId, signal?: AbortSignal): Promise<ForecastDetail> {
  if (!isAssetId(asset)) throw new ApiError(400, "invalid_asset", "Mã tài sản không hợp lệ.");
  if (config.useSample) return (await loadSample()).sampleDetail(asset);
  return apiGet<ForecastDetail>(`/forecasts/${asset}`, signal);
}

/** Độ tin cậy rolling_8w. Trạng thái ngoài enum của contract → AccuracyFormatError. */
export async function getAccuracy(asset: AssetId, signal?: AbortSignal): Promise<AccuracyResponse> {
  if (!isAssetId(asset)) throw new ApiError(400, "invalid_asset", "Mã tài sản không hợp lệ.");
  const response = config.useSample
    ? (await loadSample()).sampleAccuracy(asset, config.sampleAccuracy)
    : await apiGet<AccuracyResponse>(`/accuracy/${asset}`, signal);
  assertAccuracyStatuses(response);
  return response;
}

/**
 * Số phiên giá cuối xin kèm dự báo (tối đa của API là 520, khoảng 2 năm giao dịch). Dùng chung cho
 * trang Tổng quan giá và biểu đồ "Giá thực tế và dự báo" ở trang sản phẩm, nên hai trang dùng chung cache.
 */
export const PRICE_HISTORY_SESSIONS = 520;

/** Tên cũ, giữ để không vỡ chỗ đang import. */
export const OVERVIEW_HISTORY_SESSIONS = PRICE_HISTORY_SESSIONS;

/**
 * Chi tiết dự báo mới nhất kèm `price_history` (contract: tham số `history`). API có thể trả ít hơn
 * `sessions` điểm khi lịch sử chưa đủ dài.
 */
export async function getForecastWithHistory(
  asset: AssetId,
  sessions: number = PRICE_HISTORY_SESSIONS,
  signal?: AbortSignal,
): Promise<ForecastDetailWithHistory> {
  if (!isAssetId(asset)) throw new ApiError(400, "invalid_asset", "Mã tài sản không hợp lệ.");
  if (config.useSample) return (await loadSample()).sampleDetailWithHistory(asset, sessions);
  const detail = await apiGet<ForecastDetailWithHistory>(`/forecasts/${asset}?history=${sessions}`, signal);
  // API bản cũ (chưa có tham số history) bỏ qua query và không trả price_history: coi như chưa có điểm
  // nào để trang vẫn hiện dự báo thay vì lỗi.
  return Array.isArray(detail.price_history) ? detail : { ...detail, price_history: [] };
}
