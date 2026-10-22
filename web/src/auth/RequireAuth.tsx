import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { config } from "../api/config";
import { LoadingBlock } from "../components/StateViews";

// aws-amplify chỉ được tải khi bật đăng nhập (VITE_AUTH_ENABLED=true).
const AuthGate = lazy(() => import("./AuthGate"));

export function RequireAuth({ children }: { children: ReactNode }) {
  if (!config.authEnabled) return <>{children}</>;
  return (
    <Suspense fallback={<LoadingBlock label="Đang tải màn hình đăng nhập…" />}>
      <AuthGate>{children}</AuthGate>
    </Suspense>
  );
}
