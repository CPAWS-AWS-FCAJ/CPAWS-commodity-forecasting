import { Amplify } from "aws-amplify";
import { config } from "../api/config";
import { PASSWORD_POLICY } from "./authForm";

// Chỉ nạp khi VITE_AUTH_ENABLED=true (AmplifyAuthProvider import muộn). Dùng Cognito User Pool có
// sẵn do CDK tạo, không dùng Amplify backend.
if (!config.userPoolId || !config.userPoolClientId) {
  throw new Error("Thiếu VITE_USER_POOL_ID hoặc VITE_USER_POOL_CLIENT_ID khi bật đăng nhập.");
}

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: config.userPoolId,
      userPoolClientId: config.userPoolClientId,
      // Authenticator kiểm tra mật khẩu ngay trên form đăng ký theo đúng chính sách của pool.
      passwordFormat: PASSWORD_POLICY,
    },
  },
});
