import { useCallback, useState } from "react";
import { withViewTransition } from "../../lib/motion";

/** Khóa localStorage lưu trạng thái sidebar desktop: "collapsed" | "expanded". */
export const SIDEBAR_STORAGE_KEY = "cpaws.sidebar";

function readCollapsed(): boolean {
  // localStorage có thể ném lỗi (chế độ riêng tư, chặn dữ liệu site): mặc định mở
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "collapsed";
  } catch {
    return false;
  }
}

/**
 * Sidebar desktop thu gọn hay mở; mặc định mở, nhớ lựa chọn giữa các lần vào trang. Đổi trong một View
 * Transition (class `vt-sidebar`, xem index.css) khi trình duyệt hỗ trợ; không thì đổi tức thì.
 */
export function useSidebarCollapsed() {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const toggle = useCallback(() => {
    withViewTransition(
      () =>
        setCollapsed((prev) => {
          const next = !prev;
          try {
            window.localStorage.setItem(SIDEBAR_STORAGE_KEY, next ? "collapsed" : "expanded");
          } catch {
            // Không lưu được thì chỉ giữ trong phiên hiện tại
          }
          return next;
        }),
      "vt-sidebar",
    );
  }, []);
  return { collapsed, toggle };
}
