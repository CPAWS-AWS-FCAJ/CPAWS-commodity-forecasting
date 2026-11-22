import { isAssetId } from "../api/types";
import type { ChatCitation, ChatForecastUsed, ChatQuota, ChatResponse } from "../api/types";

/**
 * Lịch sử chat trong phiên làm việc: lưu ở `sessionStorage` (mỗi tab một bản, đóng tab/trình duyệt là
 * mất), để chuyển trang hay tải lại vẫn còn. Server không lưu hội thoại (contract mục "POST /chat").
 * Khóa theo người dùng + tài sản: `cpaws.chat.v1:<sub Cognito | "sample">:<asset>`, nên đổi tài khoản
 * không thấy chat của người khác; đăng xuất xóa mọi khóa `cpaws.chat.v1:` (clearChatHistory).
 * sessionStorage có thể ném lỗi (chặn dữ liệu site, đầy bộ nhớ): mọi truy cập bọc try/catch, dữ liệu
 * hỏng thì bỏ qua. Lượt gửi lên server vẫn theo buildHistory (3 lượt gần nhất), không đổi ở đây.
 */

export const CHAT_STORAGE_PREFIX = "cpaws.chat.v1:";
/** Tối đa 30 lượt hỏi đáp (mỗi lượt: câu hỏi + câu trả lời hoặc lỗi). */
export const MAX_STORED_ENTRIES = 60;
/** Giới hạn kích thước JSON của một hội thoại (ký tự); vượt thì bỏ dần lượt cũ nhất. */
export const MAX_STORED_CHARS = 200_000;

export type ChatEntry =
  | { id: number; at: string; kind: "user"; text: string }
  | { id: number; at: string; kind: "assistant"; response: ChatResponse }
  | { id: number; at: string; kind: "error"; text: string; resetAt?: string };

export function chatStorageKey(owner: string, asset: string): string {
  return `${CHAT_STORAGE_PREFIX}${owner}:${asset}`;
}

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const isString = (v: unknown): v is string => typeof v === "string";

function readCitation(v: unknown): ChatCitation | null {
  if (!isObject(v) || !isString(v.title) || !isString(v.link)) return null;
  return {
    title: v.title,
    link: v.link,
    source: isString(v.source) ? v.source : "",
    published_at: isString(v.published_at) ? v.published_at : "",
  };
}

function readForecastUsed(v: unknown): ChatForecastUsed | null {
  if (!isObject(v) || !isString(v.asset) || !isAssetId(v.asset)) return null;
  return {
    asset: v.asset,
    base_date: isString(v.base_date) ? v.base_date : "",
    model_version: isString(v.model_version) ? v.model_version : "",
    is_sample: v.is_sample === true,
    stale: v.stale === true,
  };
}

function readQuota(v: unknown): ChatQuota | null {
  if (!isObject(v)) return null;
  const { limit, used, remaining } = v;
  if (typeof limit !== "number" || typeof used !== "number" || typeof remaining !== "number") return null;
  return { limit, used, remaining, reset_at: isString(v.reset_at) ? v.reset_at : "" };
}

/** Kiểm lại câu trả lời đã lưu: thiếu trường chính (answer, disclaimer) thì bỏ cả lượt. */
function readResponse(v: unknown): ChatResponse | null {
  if (!isObject(v) || !isString(v.answer) || !isString(v.disclaimer)) return null;
  const citations = Array.isArray(v.citations) ? v.citations.map(readCitation) : [];
  const used = Array.isArray(v.forecasts_used) ? v.forecasts_used.map(readForecastUsed) : [];
  return {
    request_id: isString(v.request_id) ? v.request_id : "",
    answer: v.answer,
    branch: v.branch === "simple" ? "simple" : "complex",
    prompt_version: isString(v.prompt_version) ? v.prompt_version : "",
    forecasts_used: used.filter((f): f is ChatForecastUsed => f !== null),
    citations: citations.filter((c): c is ChatCitation => c !== null),
    truncated: v.truncated === true,
    blocked: v.blocked === true,
    quota: readQuota(v.quota),
    disclaimer: v.disclaimer,
  };
}

function readEntry(v: unknown): ChatEntry | null {
  if (!isObject(v) || typeof v.id !== "number" || !Number.isFinite(v.id)) return null;
  const at = isString(v.at) ? v.at : "";
  if (v.kind === "user" && isString(v.text)) return { id: v.id, at, kind: "user", text: v.text };
  if (v.kind === "error" && isString(v.text)) {
    return { id: v.id, at, kind: "error", text: v.text, ...(isString(v.resetAt) ? { resetAt: v.resetAt } : {}) };
  }
  if (v.kind === "assistant") {
    const response = readResponse(v.response);
    return response ? { id: v.id, at, kind: "assistant", response } : null;
  }
  return null;
}

/** Đọc hội thoại đã lưu; không có, bị chặn hoặc hỏng → []. Lượt hỏng bị bỏ, lượt hợp lệ giữ lại. */
export function loadChat(key: string): ChatEntry[] {
  const store = storage();
  if (!store) return [];
  let raw: string | null;
  try {
    raw = store.getItem(key);
  } catch {
    return [];
  }
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    parsed = null;
  }
  if (!isObject(parsed) || parsed.v !== 1 || !Array.isArray(parsed.entries)) {
    // Hỏng hoặc khác phiên bản: xóa để lần sau không phải đọc lại
    try {
      store.removeItem(key);
    } catch {
      // bỏ qua
    }
    return [];
  }
  return trimEntries(parsed.entries.map(readEntry).filter((e): e is ChatEntry => e !== null));
}

/** Giữ tối đa MAX_STORED_ENTRIES lượt gần nhất, cắt ở đầu một câu hỏi để không còn câu trả lời mồ côi. */
export function trimEntries(entries: readonly ChatEntry[]): ChatEntry[] {
  let kept = entries.slice(-MAX_STORED_ENTRIES);
  while (kept.length && kept[0].kind !== "user") kept = kept.slice(1);
  return kept;
}

function serialize(entries: readonly ChatEntry[]): string {
  return JSON.stringify({ v: 1, entries });
}

/** Lưu hội thoại (rỗng thì xóa khóa). Quá kích thước thì bỏ dần lượt cũ; vẫn lỗi (đầy bộ nhớ) thì thôi. */
export function saveChat(key: string, entries: readonly ChatEntry[]): void {
  const store = storage();
  if (!store) return;
  try {
    let kept = trimEntries(entries);
    let text = serialize(kept);
    while (kept.length && text.length > MAX_STORED_CHARS) {
      kept = trimEntries(kept.slice(1));
      text = serialize(kept);
    }
    if (kept.length === 0) store.removeItem(key);
    else store.setItem(key, text);
  } catch {
    // Không lưu được thì hội thoại chỉ còn trong bộ nhớ của trang
  }
}

/** Xóa mọi hội thoại đã lưu của phiên (đăng xuất, phiên hết hạn). */
export function clearChatHistory(): void {
  const store = storage();
  if (!store) return;
  try {
    const keys: string[] = [];
    for (let i = 0; i < store.length; i += 1) {
      const key = store.key(i);
      if (key?.startsWith(CHAT_STORAGE_PREFIX)) keys.push(key);
    }
    keys.forEach((key) => store.removeItem(key));
  } catch {
    // bỏ qua
  }
}
