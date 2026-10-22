// Biến môi trường công khai (VITE_*). Không bao giờ đặt khóa bí mật ở front-end.
const env = import.meta.env;

/** Không có API URL, hoặc VITE_USE_SAMPLE=true → dùng dữ liệu mẫu cục bộ. */
const useSample = env.VITE_USE_SAMPLE === "true" || !env.VITE_API_URL;

export const config = {
  apiUrl: (env.VITE_API_URL ?? "").replace(/\/+$/, ""),
  useSample,
  /**
   * Lịch sử giá: contract và API hiện CHƯA có GET /history/{asset} (Khải review PR #20), nên chỉ
   * dùng dữ liệu mẫu. Khi contract có endpoint thì đổi thành `true` (hoặc theo cờ riêng).
   */
  historyAvailable: useSample,
  /**
   * Hiển thị giá vàng/bạc (dựng từ dữ liệu Yahoo, ADR-0005). Mặc định bật cho demo nội bộ;
   * đặt VITE_SHOW_METAL_PRICES=false để vàng/bạc chỉ hiện % thay đổi và xác suất tăng.
   */
  showMetalPrices: env.VITE_SHOW_METAL_PRICES !== "false",
  authEnabled: env.VITE_AUTH_ENABLED === "true",
  region: env.VITE_REGION ?? "ap-southeast-1",
  userPoolId: env.VITE_USER_POOL_ID ?? "",
  userPoolClientId: env.VITE_USER_POOL_CLIENT_ID ?? "",
} as const;
