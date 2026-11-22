import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { flushSync } from "react-dom";
import { matchesMedia, REDUCED_MOTION } from "./media";

/**
 * Trợ giúp chuyển động (không thư viện ngoài): CSS keyframes trong index.css, View Transitions API khi
 * trình duyệt có, Web Animations API cho hiệu ứng vào trang. Môi trường không có matchMedia (test jsdom)
 * hoặc người dùng bật "giảm chuyển động" → không chạy hiệu ứng nào bằng JS, mọi thứ đổi tức thì.
 */

/** Đường cong và thời lượng dùng trong JS (khớp token CSS --ease-enter, --dur-slow). */
export const EASE_ENTER = "cubic-bezier(0.22, 1, 0.36, 1)";
export const DUR_SLOW = 320;

/** Được phép chạy hiệu ứng bằng JS: có matchMedia (trình duyệt thật) và không giảm chuyển động. */
export function canAnimate(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && !matchesMedia(REDUCED_MOTION);
}

/**
 * true trong `ms` đầu sau khi mount (khi được phép chuyển động), rồi false. Dùng cho hiệu ứng chỉ chạy
 * lần đầu (biểu đồ vẽ đường), để đổi mốc, phóng to hay đổi đơn vị sau đó cập nhật tức thì, không giật.
 */
export function useEntrance(ms = 1000): boolean {
  const [active, setActive] = useState(canAnimate);
  useEffect(() => {
    if (!active) return;
    const timer = window.setTimeout(() => setActive(false), ms);
    return () => window.clearTimeout(timer);
  }, [active, ms]);
  return active;
}

/**
 * Giữ hộp thoại trên màn thêm `ms` sau khi đóng để chạy hiệu ứng ra (CSS `[data-motion="closing"]`).
 * Không được phép chuyển động thì gỡ ngay. Trong lúc đóng, phần tử nên `inert` (không bấm/Tab được).
 */
export function useExitTransition(open: boolean, ms: number): { mounted: boolean; closing: boolean } {
  const [closing, setClosing] = useState(false);
  const wasOpen = useRef(open);

  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      setClosing(false);
      return;
    }
    if (!wasOpen.current) return;
    wasOpen.current = false;
    if (!canAnimate()) return;
    setClosing(true);
    const timer = window.setTimeout(() => setClosing(false), ms);
    return () => window.clearTimeout(timer);
  }, [open, ms]);

  return { mounted: open || closing, closing: !open && closing };
}

type ViewTransitionDocument = Document & {
  startViewTransition?: (update: () => void) => { finished: Promise<void> };
};

/**
 * Đổi giao diện trong một View Transition (trình duyệt hỗ trợ, không giảm chuyển động); `scope` là
 * class tạm gắn vào <html> để CSS chỉ đặt view-transition-name cho phần cần chuyển. Không hỗ trợ →
 * gọi `update` như bình thường.
 */
export function withViewTransition(update: () => void, scope: string): void {
  const doc = typeof document !== "undefined" ? (document as ViewTransitionDocument) : null;
  if (!doc?.startViewTransition || !canAnimate()) {
    update();
    return;
  }
  const root = doc.documentElement;
  root.classList.add(scope);
  try {
    const transition = doc.startViewTransition(() => flushSync(update));
    transition.finished.finally(() => root.classList.remove(scope));
  } catch {
    root.classList.remove(scope);
    update();
  }
}

/**
 * Nội dung trang hiện dần khi đổi đường dẫn (không chạy lần đầu vào app). Máy tính: nhô lên 6px + mờ
 * dần; điện thoại chỉ mờ dần, vì transform trên <main> làm nút chatbot `position: fixed` bên trong nhảy
 * chỗ trong lúc chạy. Dùng Web Animations API nên không phải dựng lại cây React.
 */
export function usePageEnter(ref: RefObject<HTMLElement | null>, key: string): void {
  // So với đường dẫn trước (không dùng cờ "lần đầu": StrictMode chạy effect hai lần khi mount)
  const shown = useRef(key);
  useEffect(() => {
    if (shown.current === key) return;
    shown.current = key;
    const el = ref.current;
    if (!el || typeof el.animate !== "function" || !canAnimate()) return;
    const rise = matchesMedia("(min-width: 64rem)");
    const animation = el.animate(
      rise
        ? [
            { opacity: 0, transform: "translateY(6px)" },
            { opacity: 1, transform: "none" },
          ]
        : [{ opacity: 0 }, { opacity: 1 }],
      { duration: rise ? DUR_SLOW : 220, easing: EASE_ENTER },
    );
    return () => animation.cancel();
  }, [ref, key]);
}
