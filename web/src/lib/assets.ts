import { config } from "../api/config";
import type { AssetId } from "../api/types";
import { isMetal } from "./units";

export interface AssetMeta {
  id: AssetId;
  name: string;
  /** Ghi chú chuỗi đại diện hiển thị dưới tên sản phẩm. */
  note?: string;
}

export const ASSETS: Record<AssetId, AssetMeta> = {
  gold: {
    id: "gold",
    name: "Vàng",
    note: "Dự báo dựa trên chuỗi đại diện GLD, quy đổi về USD/oz; không phải giá giao ngay.",
  },
  silver: {
    id: "silver",
    name: "Bạc",
    note: "Dự báo dựa trên chuỗi đại diện SLV, quy đổi về USD/oz; không phải giá giao ngay.",
  },
  brent: { id: "brent", name: "Dầu Brent" },
  wti: { id: "wti", name: "Dầu WTI" },
};

/**
 * Vàng/bạc không hiện giá khi VITE_SHOW_METAL_PRICES=false (ADR-0005, phương án (b)):
 * chỉ hiện % thay đổi (log return) và xác suất tăng. Dầu luôn hiện giá.
 */
export function isPriceHidden(
  asset: AssetId,
  showMetalPrices: boolean = config.showMetalPrices,
): boolean {
  return isMetal(asset) && !showMetalPrices;
}
