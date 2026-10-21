// Biến môi trường công khai (VITE_*). Không bao giờ đặt khóa bí mật ở front-end.
const env = import.meta.env;

export const config = {
  apiUrl: (env.VITE_API_URL ?? "").replace(/\/+$/, ""),
  /** Không có API URL, hoặc VITE_USE_SAMPLE=true → dùng dữ liệu mẫu cục bộ. */
  useSample: env.VITE_USE_SAMPLE === "true" || !env.VITE_API_URL,
  authEnabled: env.VITE_AUTH_ENABLED === "true",
  region: env.VITE_REGION ?? "ap-southeast-1",
  userPoolId: env.VITE_USER_POOL_ID ?? "",
  userPoolClientId: env.VITE_USER_POOL_CLIENT_ID ?? "",
} as const;
