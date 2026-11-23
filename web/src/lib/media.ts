import { useSyncExternalStore } from "react";

/** Khớp media query; môi trường không có matchMedia (test jsdom, SSR) coi như không khớp. */
export function matchesMedia(query: string): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(query).matches
    : false;
}

/** Theo dõi một media query, render lại khi đổi (xoay màn, cắm chuột…). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
      const list = window.matchMedia(query);
      list.addEventListener?.("change", onChange);
      return () => list.removeEventListener?.("change", onChange);
    },
    () => matchesMedia(query),
    () => false,
  );
}

/** Thiết bị nhập chính là cảm ứng (ngón tay): cần vùng chạm lớn, không có phím. */
export const COARSE_POINTER = "(pointer: coarse)";

/** Người dùng muốn giảm chuyển động: cuộn tức thì thay vì cuộn mượt. */
export const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";
