import { createContext, useContext } from "react";

// Module nhẹ: không import aws-amplify, để bản chạy dữ liệu mẫu (VITE_AUTH_ENABLED=false) không
// phải tải thư viện đăng nhập.

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

/** Thuộc tính tài khoản đọc từ Cognito (`fetchUserAttributes` + `getCurrentUser`). */
export interface Account {
  name?: string;
  email?: string;
  username?: string;
  /** `sub` của Cognito (getCurrentUser().userId): khóa lịch sử chat trong phiên theo người dùng. */
  userId?: string;
}

export interface AuthState {
  status: AuthStatus;
  /** VITE_AUTH_ENABLED=false: coi như đã đăng nhập, chạy với dữ liệu mẫu (local, test). */
  sampleMode: boolean;
  account: Account | null;
  signOut: () => Promise<void>;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth phải nằm trong <AuthProvider>");
  return value;
}

/** Trạng thái cố định khi tắt đăng nhập. */
export const SAMPLE_AUTH: AuthState = {
  status: "authenticated",
  sampleMode: true,
  account: null,
  signOut: async () => {},
};

/** Trạng thái trong lúc tải module đăng nhập. */
export const LOADING_AUTH: AuthState = {
  status: "loading",
  sampleMode: false,
  account: null,
  signOut: async () => {},
};

/**
 * Tên hiển thị trong sidebar: Họ tên (`name`) → email (tài khoản cũ chưa có `name`) → tên đăng nhập
 * (chỉ khi không còn gì khác). Chuỗi rỗng hoặc toàn khoảng trắng coi như không có.
 */
export function displayName(account: Account | null | undefined): string | null {
  if (!account) return null;
  for (const value of [account.name, account.email, account.username]) {
    const text = value?.trim();
    if (text) return text;
  }
  return null;
}
