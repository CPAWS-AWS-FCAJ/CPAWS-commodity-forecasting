import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { UNAUTHORIZED_EVENT } from "../api/client";
import { signInPath } from "./redirect";

/**
 * API trả 401 (api/client.ts phát UNAUTHORIZED_EVENT) → đăng xuất → về /dang-nhap?next=<trang đang
 * xem>. Nhiều request 401 cùng lúc chỉ xử lý một lần.
 */
export function useUnauthorizedRedirect(signOut: () => Promise<void>): void {
  const navigate = useNavigate();
  const location = useLocation();
  const currentPath = useRef("/");
  const handling = useRef(false);

  useEffect(() => {
    currentPath.current = `${location.pathname}${location.search}`;
  }, [location.pathname, location.search]);

  useEffect(() => {
    const onUnauthorized = () => {
      if (handling.current) return;
      handling.current = true;
      const target = signInPath(currentPath.current);
      signOut()
        .catch(() => {
          // Đăng xuất lỗi (mạng) vẫn đưa về trang đăng nhập
        })
        .finally(() => {
          handling.current = false;
          navigate(target, { replace: true });
        });
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [navigate, signOut]);
}
