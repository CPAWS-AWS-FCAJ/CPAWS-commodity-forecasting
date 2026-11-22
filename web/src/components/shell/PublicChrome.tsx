import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { config } from "../../api/config";
import { signInPath } from "../../auth/redirect";
import { Disclaimer } from "../Disclaimer";
import { ThemeToggle } from "./ThemeToggle";
import { Wordmark } from "./Wordmark";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-2 text-sm transition-colors duration-150 ${
    isActive ? "text-price" : "text-muted hover:text-price"
  }`;

/** Nút chính và phụ dùng chung cho trang công khai (một kiểu nút cho cả trang). */
export const PRIMARY_BUTTON =
  "inline-flex h-11 items-center justify-center whitespace-nowrap rounded-md bg-price px-5 text-sm font-medium text-on-price transition-[opacity,transform] duration-150 hover:opacity-90 active:translate-y-px motion-reduce:transition-none";
export const SECONDARY_BUTTON =
  "inline-flex h-11 items-center justify-center whitespace-nowrap rounded-md border border-line bg-surface px-5 text-sm font-medium text-price transition-[background-color,transform] duration-150 hover:bg-surface-muted active:translate-y-px motion-reduce:transition-none";

/**
 * Thanh trên của trang công khai (giới thiệu, đăng nhập): tên sản phẩm, hai trang công khai, công tắc
 * giao diện tối, nút Đăng nhập/Tạo tài khoản. Dưới sm, hai liên kết trang chuyển xuống chân trang.
 */
export function PublicHeader({ showAuthActions = true }: { showAuthActions?: boolean }) {
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-2 px-4 sm:px-6 lg:px-10">
        <Wordmark />
        <nav aria-label="Trang công khai" className="ml-4 hidden items-center sm:flex">
          <NavLink to="/guide" className={linkClass}>
            Cách đọc dự báo
          </NavLink>
          <NavLink to="/about" className={linkClass}>
            Giới thiệu
          </NavLink>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle variant="icon" />
          {showAuthActions ? (
            <>
              <Link
                to={signInPath()}
                className="inline-flex h-9 items-center rounded-md px-3 text-sm font-medium text-price transition-colors duration-150 hover:bg-surface-muted"
              >
                Đăng nhập
              </Link>
              {config.allowSignUp ? (
                <Link
                  to={signInPath(undefined, { signUp: true })}
                  className="hidden h-9 items-center rounded-md bg-price px-3 text-sm font-medium text-on-price transition-opacity duration-150 hover:opacity-90 sm:inline-flex"
                >
                  Tạo tài khoản
                </Link>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
    </header>
  );
}

export function PublicFooter({ showDisclaimer = true }: { showDisclaimer?: boolean }) {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-6 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-10">
        {showDisclaimer ? <Disclaimer /> : <p className="text-xs text-muted">CPAWS</p>}
        <nav aria-label="Liên kết chân trang" className="flex gap-4 text-xs">
          <Link to="/guide" className="text-muted underline-offset-4 hover:text-price hover:underline">
            Cách đọc dự báo
          </Link>
          <Link to="/about" className="text-muted underline-offset-4 hover:text-price hover:underline">
            Giới thiệu
          </Link>
        </nav>
      </div>
    </footer>
  );
}

export function PublicShell({
  children,
  showAuthActions = true,
  footerDisclaimer = true,
}: {
  children: ReactNode;
  showAuthActions?: boolean;
  /** Trang đã có câu miễn trừ trong nội dung thì không lặp ở chân trang. */
  footerDisclaimer?: boolean;
}) {
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:text-price focus:ring-1 focus:ring-line"
      >
        Bỏ qua điều hướng
      </a>
      <PublicHeader showAuthActions={showAuthActions} />
      <main id="main" tabIndex={-1} className="flex-1">
        {children}
      </main>
      <PublicFooter showDisclaimer={footerDisclaimer} />
    </div>
  );
}
