import { Authenticator } from "@aws-amplify/ui-react";
import "@aws-amplify/ui-react/styles.css";
import { signOut } from "aws-amplify/auth";
import { useEffect } from "react";
import type { ReactNode } from "react";
import { UNAUTHORIZED_EVENT } from "../api/client";
import "./amplify";

/** Chặn toàn bộ ứng dụng sau màn hình đăng nhập Cognito. API trả 401 → đăng xuất, về màn hình đăng nhập. */
export default function AuthGate({ children }: { children: ReactNode }) {
  useEffect(() => {
    const onUnauthorized = () => {
      void signOut();
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  // hideSignUp: giả định tài khoản do Tuấn tạo trong User Pool (cần xác nhận).
  return (
    <Authenticator hideSignUp>{() => <>{children}</>}</Authenticator>
  );
}
