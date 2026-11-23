import { useRef } from "react";
import type { ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { usePageEnter } from "../lib/motion";
import { Disclaimer } from "./Disclaimer";
import { MenuButton, NavDrawer, SIDEBAR_ID, SidebarContent, useMobileMenu } from "./shell/MobileMenu";
import { useSidebarCollapsed } from "./shell/sidebarPreference";
import { ThemeToggle } from "./shell/ThemeToggle";
import { Wordmark } from "./shell/Wordmark";

/**
 * Khung app: sidebar dọc bên trái từ lg, dưới lg là thanh trên + nút mở menu dạng ngăn kéo (dùng chung
 * với trang công khai, xem shell/MobileMenu.tsx). Sidebar desktop thu gọn được thành dải hẹp 4.5rem
 * (nhớ trong localStorage `cpaws.sidebar`); nội dung chính giãn ra theo. Cột đổi một lần (không animate
 * grid nên chữ không nhảy dòng từng khung hình); trình duyệt có View Transitions thì sidebar và nội dung
 * chuyển mượt bằng ảnh chụp (xem index.css, sidebarPreference.ts). Đổi trang: nội dung hiện dần.
 * `children` dùng khi trang không đi qua route lồng (trang chủ đã đăng nhập), còn lại là <Outlet />.
 */
export function Layout({ children }: { children?: ReactNode }) {
  const menu = useMobileMenu();
  const sidebar = useSidebarCollapsed();
  const mainRef = useRef<HTMLElement>(null);
  usePageEnter(mainRef, useLocation().pathname);
  // Thu gọn sidebar thì nới giới hạn bề rộng để nội dung thật sự giãn ra (trang chữ tự giới hạn max-w-prose)
  const width = sidebar.collapsed ? "max-w-6xl lg:max-w-[88rem]" : "max-w-6xl 2xl:max-w-7xl";

  return (
    <div
      // data-sidebar + group/app: trang con (cột chat của AssetPage) giãn thêm khi sidebar thu gọn
      data-sidebar={sidebar.collapsed ? "collapsed" : "expanded"}
      className={`group/app min-h-dvh lg:grid ${
        sidebar.collapsed ? "lg:grid-cols-[4.5rem_minmax(0,1fr)]" : "lg:grid-cols-[15.5rem_minmax(0,1fr)]"
      }`}
    >
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:text-price focus:ring-1 focus:ring-line"
      >
        Bỏ qua điều hướng
      </a>

      {/* Cột nền kéo hết chiều cao trang; phần trong dính ở đầu màn hình khi cuộn */}
      <aside id={SIDEBAR_ID} className="hidden border-r border-line bg-surface lg:block">
        <div className="sticky top-0 flex h-dvh flex-col">
          <SidebarContent sidebarToggle={{ collapsed: sidebar.collapsed, onToggle: sidebar.toggle }} />
        </div>
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-line bg-surface px-3 lg:hidden">
        <MenuButton menu={menu} />
        <Wordmark />
        <div className="ml-auto">
          <ThemeToggle variant="icon" />
        </div>
      </header>

      <NavDrawer menu={menu} />

      <div id="app-content" className="flex min-w-0 flex-col">
        <main
          ref={mainRef}
          id="main"
          tabIndex={-1}
          className={`mx-auto w-full flex-1 px-4 py-6 sm:px-6 lg:px-10 lg:py-10 ${width}`}
        >
          {children ?? <Outlet />}
        </main>
        <footer className={`mx-auto w-full px-4 pb-6 sm:px-6 lg:px-10 ${width}`}>
          <div className="border-t border-line pt-4">
            <Disclaimer />
          </div>
        </footer>
      </div>
    </div>
  );
}
