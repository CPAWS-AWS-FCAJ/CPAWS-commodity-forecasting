import type { AssetId } from "../api/types";

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
