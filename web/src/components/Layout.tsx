import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Disclaimer } from "./Disclaimer";
import { AccountBlock } from "./shell/AccountBlock";
import { CloseIcon, MenuIcon } from "./shell/icons";
import { MobileDrawer } from "./shell/MobileDrawer";
import { SidebarNav } from "./shell/SidebarNav";
import { ThemeToggle } from "./shell/ThemeToggle";
import { Wordmark } from "./shell/Wordmark";

const DRAWER_ID = "menu-dieu-huong";

/** Nội dung dùng chung cho sidebar desktop và ngăn kéo mobile. */
function SidebarContent({ onNavigate, onClose }: { onNavigate?: () => void; onClose?: () => void }) {
  return (
    <>
      <div className="flex h-16 shrink-0 items-center justify-between gap-2 px-5">
        <Wordmark onClick={onNavigate} withTagline />
        {onClose ? (
          <button
            type="button"
            data-autofocus
            onClick={onClose}
            aria-label="Đóng menu"
            className="inline-flex size-9 items-center justify-center rounded-md text-muted transition-colors duration-150 hover:bg-surface-muted hover:text-price active:bg-line"
          >
            <CloseIcon />
          </button>
        ) : null}
      </div>
      <nav aria-label="Điều hướng chính" className="min-h-0 flex-1 overflow-y-auto px-3 pb-6 pt-2">
        <SidebarNav onNavigate={onNavigate} />
      </nav>
      <div className="shrink-0 border-t border-line p-3">
        <AccountBlock onNavigate={onNavigate} />
      </div>
    </>
  );
}

/**
 * Khung app: sidebar dọc bên trái từ lg, dưới lg là thanh trên + nút mở menu dạng ngăn kéo.
 * `children` dùng khi trang không đi qua route lồng (trang chủ đã đăng nhập), còn lại là <Outlet />.
 */
export function Layout({ children }: { children?: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const location = useLocation();
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  // Đổi trang (kể cả nút Quay lại của trình duyệt) thì đóng menu.
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15.5rem_minmax(0,1fr)]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:text-price focus:ring-1 focus:ring-line"
      >
        Bỏ qua điều hướng
      </a>

      {/* Cột nền kéo hết chiều cao trang; phần trong dính ở đầu màn hình khi cuộn */}
      <aside className="hidden border-r border-line bg-surface lg:block">
        <div className="sticky top-0 flex h-dvh flex-col">
          <SidebarContent />
        </div>
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-line bg-surface px-3 lg:hidden">
        <button
          ref={menuButtonRef}
          type="button"
          onClick={() => setMenuOpen(true)}
          aria-expanded={menuOpen}
          aria-controls={DRAWER_ID}
          aria-label="Mở menu"
          className="inline-flex size-9 items-center justify-center rounded-md text-price transition-colors duration-150 hover:bg-surface-muted active:bg-line"
        >
          <MenuIcon />
        </button>
        <Wordmark />
        <div className="ml-auto">
          <ThemeToggle variant="icon" />
        </div>
      </header>

      <MobileDrawer
        id={DRAWER_ID}
        open={menuOpen}
        onClose={closeMenu}
        returnFocusRef={menuButtonRef}
        label="Menu điều hướng"
      >
        <SidebarContent onNavigate={closeMenu} onClose={closeMenu} />
      </MobileDrawer>

      <div className="flex min-w-0 flex-col">
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 lg:px-10 lg:py-10">
          {children ?? <Outlet />}
        </main>
        <footer className="mx-auto w-full max-w-6xl px-4 pb-6 sm:px-6 lg:px-10">
          <div className="border-t border-line pt-4">
            <Disclaimer />
          </div>
        </footer>
      </div>
    </div>
  );
}
