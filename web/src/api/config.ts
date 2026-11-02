// Biến môi trường công khai (VITE_*). Không bao giờ đặt khóa bí mật ở front-end.
const env = import.meta.env;

/** Không có API URL, hoặc VITE_USE_SAMPLE=true → dùng dữ liệu mẫu cục bộ. */
const useSample = env.VITE_USE_SAMPLE === "true" || !env.VITE_API_URL;

export type SampleAccuracy = "not_ready" | "collecting" | "ready";

function parseSampleAccuracy(value: string | undefined): SampleAccuracy {
  return value === "not_ready" || value === "ready" ? value : "collecting";
}

export const config = {
  apiUrl: (env.VITE_API_URL ?? "").replace(/\/+$/, ""),
  useSample,
  /**
   * Lịch sử giá: contract và API hiện CHƯA có GET /history/{asset} (Khải review PR #20), nên chỉ
   * dùng dữ liệu mẫu. Khi contract có endpoint thì đổi thành `true` (hoặc theo cờ riêng).
   */
  historyAvailable: useSample,
  /**
   * Chế độ mẫu: fixture GET /accuracy dùng để xem giao diện (tests/fixtures/accuracy/, synthetic).
   * Mặc định "collecting" vì chưa giả định `ready` trước 22/11.
   */
  sampleAccuracy: parseSampleAccuracy(env.VITE_SAMPLE_ACCURACY),
  /**
   * Hiển thị giá vàng/bạc (dựng từ dữ liệu Yahoo, ADR-0005). Mặc định TẮT (phương án dự phòng đang
   * áp dụng): vàng/bạc chỉ hiện % thay đổi và xác suất tăng. Chỉ bật khi VITE_SHOW_METAL_PRICES=true.
   */
  showMetalPrices: env.VITE_SHOW_METAL_PRICES === "true",
  authEnabled: env.VITE_AUTH_ENABLED === "true",
  region: env.VITE_REGION ?? "ap-southeast-1",
  userPoolId: env.VITE_USER_POOL_ID ?? "",
  userPoolClientId: env.VITE_USER_POOL_CLIENT_ID ?? "",
} as const;
