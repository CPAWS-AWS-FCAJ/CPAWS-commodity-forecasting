import { lazy, Suspense } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { config } from "../api/config";
import { Disclaimer } from "./Disclaimer";

// Nút đăng xuất kéo theo aws-amplify nên chỉ nạp khi bật đăng nhập.
const SignOutButton = lazy(() => import("../auth/SignOutButton"));

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm ${isActive ? "bg-price text-white" : "text-price hover:bg-canvas"}`;

export function Layout() {
  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:rounded focus:bg-white focus:p-2"
      >
        Bỏ qua điều hướng
      </a>
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-3">
          <NavLink to="/" className="text-lg font-bold tracking-tight">
            CPAWS
          </NavLink>
          <nav aria-label="Điều hướng chính" className="flex items-center gap-1">
            <NavLink to="/" end className={linkClass}>
              Trang chủ
            </NavLink>
            <NavLink to="/accuracy" className={linkClass}>
              Độ chính xác
            </NavLink>
            <NavLink to="/about" className={linkClass}>
              Giới thiệu
            </NavLink>
            {config.authEnabled ? (
              <Suspense fallback={null}>
                <SignOutButton />
              </Suspense>
            ) : null}
          </nav>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <Outlet />
      </main>
      <footer className="border-t border-line bg-white">
        <div className="mx-auto max-w-6xl px-4 py-4">
          <Disclaimer />
        </div>
      </footer>
    </div>
  );
}
