import { Authenticator, useAuthenticator } from "@aws-amplify/ui-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchUserAttributes, getCurrentUser, signOut as amplifySignOut } from "aws-amplify/auth";
import { useCallback, useEffect, useMemo } from "react";
import type { ReactNode } from "react";
import { AuthContext } from "./AuthContext";
import type { Account, AuthState, AuthStatus } from "./AuthContext";
import { useUnauthorizedRedirect } from "./useUnauthorizedRedirect";
import "./amplify";

/** Khóa React Query của thuộc tính tài khoản; xóa khi đăng xuất. */
export const ACCOUNT_QUERY_KEY = ["auth", "account"] as const;

async function loadAccount(): Promise<Account> {
  const user = await getCurrentUser();
  // Thiếu quyền đọc thuộc tính (hiếm) thì vẫn có tên đăng nhập để hiển thị.
  const attributes = await fetchUserAttributes().catch(() => ({}) as Record<string, string | undefined>);
  return { username: user.username, name: attributes.name, email: attributes.email };
}

function mapStatus(status: string): AuthStatus {
  if (status === "authenticated") return "authenticated";
  if (status === "unauthenticated") return "unauthenticated";
  return "loading";
}

/** Nối trạng thái của Amplify (`authStatus`, cập nhật qua Hub) vào AuthContext của app. */
function AuthBridge({ children }: { children: ReactNode }) {
  const { authStatus } = useAuthenticator((context) => [context.authStatus]);
  const status = mapStatus(authStatus);
  const queryClient = useQueryClient();

  const account = useQuery({
    queryKey: ACCOUNT_QUERY_KEY,
    queryFn: loadAccount,
    enabled: status === "authenticated",
    staleTime: Infinity,
    retry: false,
  });

  // Đăng xuất (hoặc phiên hết hạn): bỏ toàn bộ cache, kể cả dữ liệu giá và tên người dùng trước.
  useEffect(() => {
    if (status === "unauthenticated") queryClient.removeQueries();
  }, [status, queryClient]);

  const signOut = useCallback(async () => {
    await amplifySignOut();
    queryClient.removeQueries();
  }, [queryClient]);

  useUnauthorizedRedirect(signOut);

  const value = useMemo<AuthState>(
    () => ({
      status,
      sampleMode: false,
      account: status === "authenticated" ? (account.data ?? null) : null,
      signOut,
    }),
    [status, account.data, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export default function AmplifyAuthProvider({ children }: { children: ReactNode }) {
  // Một Provider cho cả app: Authenticator ở /dang-nhap dùng lại máy trạng thái này.
  return (
    <Authenticator.Provider>
      <AuthBridge>{children}</AuthBridge>
    </Authenticator.Provider>
  );
}
