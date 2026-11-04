import { config } from "./config";
import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /**
   * Thân lỗi JSON gốc (nếu có), ví dụ `reset_at` của 429 rate_limited. Lỗi do API Gateway tự sinh
   * (401, 429 throttling, 504) chỉ có `{"message": ...}` tiếng Anh: không hiển thị nguyên văn.
   */
  readonly body: Record<string, unknown>;

  constructor(status: number, code: string, message: string, body: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.body = body;
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

async function request<T>(path: string, init: RequestInit, fallback: string): Promise<T> {
  const response = await fetch(`${config.apiUrl}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init.headers, ...(await authHeaders()) },
  });

  if (response.ok) return (await response.json()) as T;

  if (response.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));

  let body: Partial<ApiErrorBody> & Record<string, unknown> = {};
  try {
    const parsed: unknown = await response.json();
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      body = parsed as Partial<ApiErrorBody> & Record<string, unknown>;
    }
  } catch {
    // thân phản hồi không phải JSON: dùng thông báo mặc định
  }
  const code = typeof body.error === "string" ? body.error : `http_${response.status}`;
  // Chỉ dùng message của Lambda (thân dạng chung có "error"); thân mặc định của API Gateway là
  // tiếng Anh nên thay bằng câu mặc định.
  const serverMessage =
    typeof body.error === "string" && typeof body.message === "string" ? body.message : fallback;
  throw new ApiError(response.status, code, messageForStatus(response.status, serverMessage), body);
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { signal }, "Không tải được dữ liệu.");
}

export async function apiPost<T>(path: string, payload: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    },
    "Đã có lỗi, bạn thử lại sau.",
  );
}
