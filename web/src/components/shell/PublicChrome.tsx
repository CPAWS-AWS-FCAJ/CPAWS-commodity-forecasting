import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { config } from "../../api/config";
import { useAuth } from "../../auth/AuthContext";
import { signInPath } from "../../auth/redirect";
import { Disclaimer } from "../Disclaimer";
import { LockMark } from "./LockMark";
import { MenuButton, NavDrawer, useMobileMenu } from "./MobileMenu";
import { ThemeToggle } from "./ThemeToggle";
import { Wordmark } from "./Wordmark";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-sm transition-colors duration-150 ${
    isActive ? "text-price" : "text-muted hover:text-price"
  }`;

/** Nút chính và phụ dùng chung cho trang công khai (một kiểu nút cho cả trang). */
export const PRIMARY_BUTTON =
  "inline-flex h-11 items-center justify-center whitespace-nowrap rounded-md bg-price px-5 text-sm font-medium text-on-price transition-[opacity,transform] duration-150 hover:opacity-90 active:translate-y-px motion-reduce:transition-none";
export const SECONDARY_BUTTON =
  "inline-flex h-11 items-center justify-center whitespace-nowrap rounded-md border border-line bg-surface px-5 text-sm font-medium text-price transition-[background-color,transform] duration-150 hover:bg-surface-muted active:translate-y-px motion-reduce:transition-none";

/**
 * Thanh trên của trang công khai (giới thiệu, đăng nhập): tên sản phẩm, hai trang công khai, công tắc
 * giao diện tối, nút Đăng nhập/Tạo tài khoản. Dưới lg giống thanh trên của app: nút menu mở cùng ngăn
 * kéo (đủ mục, ổ khóa cho mục cần đăng nhập, Đăng nhập/Tạo tài khoản, giao diện tối), dính khi cuộn.
 */
export function PublicHeader({ showAuthActions = true }: { showAuthActions?: boolean }) {
  const menu = useMobileMenu();
  // "Cách đọc dự báo" cần đăng nhập: link vẫn giữ (RequireAuth đưa tới /dang-nhap?next=/guide), kèm ổ khóa
  const guideLocked = useAuth().status !== "authenticated";
  return (
    <>
    <header className="sticky top-0 z-30 border-b border-line bg-surface lg:static">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-2 px-3 sm:px-6 lg:px-10">
        <MenuButton menu={menu} />
        <Wordmark />
        <nav aria-label="Trang công khai" className="ml-4 hidden items-center lg:flex">
          <NavLink to="/guide" className={linkClass}>
            Cách đọc dự báo
            {guideLocked ? <LockMark /> : null}
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
                className="inline-flex h-9 items-center rounded-md px-3 text-sm font-medium text-price transition-colors duration-150 hover:bg-surface-muted pointer-coarse:h-11"
              >
                Đăng nhập
              </Link>
              {config.allowSignUp ? (
                <Link
                  to={signInPath(undefined, { signUp: true })}
                  className="hidden h-9 items-center rounded-md bg-price px-3 text-sm font-medium text-on-price transition-opacity duration-150 hover:opacity-90 sm:inline-flex pointer-coarse:h-11"
                >
                  Tạo tài khoản
                </Link>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
    </header>
    <NavDrawer menu={menu} />
    </>
  );
}

/** Link chân trang: chữ nhỏ nhưng vùng chạm 44 px trên màn cảm ứng. */
const FOOTER_LINK =
  "text-muted underline-offset-4 hover:text-price hover:underline pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center";

export function PublicFooter({ showDisclaimer = true }: { showDisclaimer?: boolean }) {
  const guideLocked = useAuth().status !== "authenticated";
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-6 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-10">
        {showDisclaimer ? <Disclaimer /> : <p className="text-xs text-muted">CPAWS</p>}
        <nav aria-label="Liên kết chân trang" className="flex gap-4 text-xs">
          <Link to="/guide" className={`${FOOTER_LINK} inline-flex items-center gap-1`}>
            Cách đọc dự báo
            {guideLocked ? <LockMark /> : null}
          </Link>
          <Link to="/about" className={FOOTER_LINK}>
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
