import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { LoadingBlock } from "../components/StateViews";
import { useAuth } from "./AuthContext";
import { signInPath } from "./redirect";

/**
 * Chặn trang cần dữ liệu giá (ADR-0005: giá chỉ hiện sau đăng nhập). Chưa đăng nhập → chuyển tới
 * /dang-nhap?next=<đường dẫn đang mở, gồm cả query và #anchor>. Tắt đăng nhập (dữ liệu mẫu) thì luôn
 * cho vào.
 * Dùng làm route bao (`<Route element={<RequireAuth />}>`) hoặc bọc `children`.
 */
export function RequireAuth({ children }: { children?: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <LoadingBlock label="Đang kiểm tra đăng nhập…" />;
  if (status !== "authenticated") {
    return <Navigate to={signInPath(`${location.pathname}${location.search}${location.hash}`)} replace />;
  }
  return children ? <>{children}</> : <Outlet />;
}
