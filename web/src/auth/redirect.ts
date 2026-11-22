/** Đường dẫn trang đăng nhập (tab Đăng nhập/Đăng ký của Authenticator). */
export const SIGN_IN_PATH = "/dang-nhap";

/** Giá trị `tab` trên URL để mở thẳng tab Đăng ký. */
export const SIGN_UP_TAB = "dang-ky";

// Gốc giả chỉ để phân tích đường dẫn; không bao giờ điều hướng tới đây.
const PARSE_BASE = "https://cpaws.invalid";

/**
 * Chỉ nhận đường dẫn nội bộ bắt đầu bằng một dấu "/" (chống open redirect). Từ chối URL tuyệt đối,
 * "//host", "/\host", ký tự điều khiển (trình duyệt bỏ tab/xuống dòng nên "/\t/host" thành "//host")
 * và chính trang đăng nhập (tránh vòng lặp). Sai thì về trang chủ.
 */
export function safeNextPath(raw: string | null | undefined, fallback = "/"): string {
  if (!raw || raw.length > 2048) return fallback;
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return fallback;
  if (/[\u0000-\u001f\u007f\\]/.test(raw)) return fallback;
  let url: URL;
  try {
    url = new URL(raw, PARSE_BASE);
  } catch {
    return fallback;
  }
  if (url.origin !== PARSE_BASE) return fallback;
  if (url.pathname === SIGN_IN_PATH || url.pathname.startsWith(`${SIGN_IN_PATH}/`)) return fallback;
  return `${url.pathname}${url.search}${url.hash}`;
}

/** `/dang-nhap?next=<đường dẫn>`; bỏ `next` khi là trang chủ. */
export function signInPath(next?: string, options: { signUp?: boolean } = {}): string {
  const params = new URLSearchParams();
  const target = safeNextPath(next);
  if (target !== "/") params.set("next", target);
  if (options.signUp) params.set("tab", SIGN_UP_TAB);
  const query = params.toString();
  return query ? `${SIGN_IN_PATH}?${query}` : SIGN_IN_PATH;
}
