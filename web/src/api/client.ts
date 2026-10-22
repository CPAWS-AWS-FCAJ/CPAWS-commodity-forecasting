import { config } from "./config";
import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** Sự kiện phát ra khi API trả 401; AuthGate lắng nghe để đưa người dùng về trang đăng nhập. */
export const UNAUTHORIZED_EVENT = "cpaws:unauthorized";

async function authHeaders(): Promise<Record<string, string>> {
  if (!config.authEnabled) return {};
  // Nạp muộn để bản không bật đăng nhập không kéo theo aws-amplify.
  const { fetchAuthSession } = await import("aws-amplify/auth");
  const session = await fetchAuthSession();
  const token = session.tokens?.idToken?.toString();
  // Cognito authorizer mặc định nhận ID token ở header Authorization (không có "Bearer").
  return token ? { Authorization: token } : {};
}

function messageForStatus(status: number, fallback: string): string {
  if (status === 429) return "Bạn đã hỏi quá nhiều, thử lại sau.";
  if (status === 401) return "Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại.";
  return fallback;
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${config.apiUrl}${path}`, {
    headers: { Accept: "application/json", ...(await authHeaders()) },
    signal,
  });

  if (response.ok) return (await response.json()) as T;

  if (response.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));

  let body: Partial<ApiErrorBody> = {};
  try {
    body = (await response.json()) as Partial<ApiErrorBody>;
  } catch {
    // thân phản hồi không phải JSON: dùng thông báo mặc định
  }
  throw new ApiError(
    response.status,
    body.error ?? `http_${response.status}`,
    messageForStatus(response.status, body.message ?? "Không tải được dữ liệu."),
  );
}
