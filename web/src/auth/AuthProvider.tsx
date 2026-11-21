import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { config } from "../api/config";
import { AuthContext, LOADING_AUTH, SAMPLE_AUTH } from "./AuthContext";

// aws-amplify chỉ được tải khi bật đăng nhập (VITE_AUTH_ENABLED=true).
const AmplifyAuthProvider = lazy(() => import("./AmplifyAuthProvider"));

/**
 * Cung cấp trạng thái đăng nhập cho toàn app. Không chặn trang công khai: trong lúc tải module
 * Amplify, trạng thái là "loading" (trang cần đăng nhập hiện khối đang tải, trang công khai hiện luôn).
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  if (!config.authEnabled) {
    return <AuthContext.Provider value={SAMPLE_AUTH}>{children}</AuthContext.Provider>;
  }
  return (
    <Suspense fallback={<AuthContext.Provider value={LOADING_AUTH}>{children}</AuthContext.Provider>}>
      <AmplifyAuthProvider>{children}</AmplifyAuthProvider>
    </Suspense>
  );
}
