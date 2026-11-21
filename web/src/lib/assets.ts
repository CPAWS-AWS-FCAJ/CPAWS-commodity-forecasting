import { config } from "../api/config";
import type { AssetId } from "../api/types";
import { isMetal } from "./units";

export interface AssetMeta {
  id: AssetId;
  name: string;
  /** Ghi chú chuỗi đại diện hiển thị dưới tên sản phẩm. */
  note?: string;
  /** Mã chuỗi target (ADR-0005), hiển thị nhỏ cạnh tên. */
  series: string;
  /** Mô tả chuỗi theo dõi, không có con số (dùng được ở trang công khai). */
  seriesLabel: string;
}

export const ASSETS: Record<AssetId, AssetMeta> = {
  gold: {
    id: "gold",
    name: "Vàng",
    note: "Dự báo dựa trên chuỗi đại diện GLD, quy đổi về USD/oz; không phải giá giao ngay.",
    series: "GLD",
    seriesLabel: "Quỹ vàng GLD (chuỗi đại diện), quy đổi về USD/oz",
  },
  silver: {
    id: "silver",
    name: "Bạc",
    note: "Dự báo dựa trên chuỗi đại diện SLV, quy đổi về USD/oz; không phải giá giao ngay.",
    series: "SLV",
    seriesLabel: "Quỹ bạc SLV (chuỗi đại diện), quy đổi về USD/oz",
  },
  brent: {
    id: "brent",
    name: "Dầu Brent",
    series: "BZ=F",
    seriesLabel: "Hợp đồng tương lai Brent, USD/thùng",
  },
  wti: {
    id: "wti",
    name: "Dầu WTI",
    series: "CL=F",
    seriesLabel: "Hợp đồng tương lai WTI, USD/thùng",
  },
};

/**
 * Màu nhận diện từng sản phẩm (token trong index.css), chỉ làm điểm nhấn nhỏ: chấm cạnh tên, viền
 * khi rê chuột. Viết đủ tên lớp để Tailwind sinh CSS. Không dùng làm màu chữ (tương phản thấp).
 */
export const ASSET_DOT_CLASS: Record<AssetId, string> = {
  gold: "bg-gold",
  silver: "bg-silver",
  brent: "bg-brent",
  wti: "bg-wti",
};

export const ASSET_HOVER_BORDER_CLASS: Record<AssetId, string> = {
  gold: "hover:border-gold",
  silver: "hover:border-silver",
  brent: "hover:border-brent",
  wti: "hover:border-wti",
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
