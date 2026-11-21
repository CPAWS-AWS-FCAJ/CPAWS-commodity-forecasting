import type { AssetId } from "../api/types";

/**
 * Màu biểu đồ dạng CSS variable (SVG của Recharts nhận var(...)), nên tự đổi theo giao diện
 * sáng/tối mà không cần render lại. Token gốc ở src/index.css, theo skill forecast-charts.
 */
export const CHART = {
  price: "var(--color-price)",
  forecast: "var(--color-forecast)",
  band: "var(--color-band)",
  medianDot: "var(--color-median-dot)",
  up: "var(--color-up)",
  down: "var(--color-down)",
  muted: "var(--color-muted)",
  grid: "var(--color-line)",
  surface: "var(--color-surface)",
} as const;

/** Màu nhận diện từng sản phẩm (CSS variable). */
export const ASSET_COLOR: Record<AssetId, string> = {
  gold: "var(--color-gold)",
  silver: "var(--color-silver)",
  brent: "var(--color-brent)",
  wti: "var(--color-wti)",
};
