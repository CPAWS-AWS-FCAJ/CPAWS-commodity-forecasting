import { SOURCE_ATTRIBUTION } from "../lib/source";

/** Dòng nguồn dữ liệu giá, đặt ở mọi màn hình có giá (trang chủ, trang tài sản, Giới thiệu). */
export function SourceNote({ className = "" }: { className?: string }) {
  return <p className={`text-xs text-muted ${className}`.trim()}>{SOURCE_ATTRIBUTION}</p>;
}
