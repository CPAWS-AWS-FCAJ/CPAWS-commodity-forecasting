// POST /chat theo docs/api/contract.md (mục "POST /chat"). Server không lưu hội thoại: web giữ lịch
// sử trong bộ nhớ của trang và tự gửi tối đa 6 phần tử gần nhất.
import { apiPost, ApiError } from "./client";
import type { AssetId, ChatCitation, ChatHistoryItem, ChatResponse } from "./types";

export const MAX_QUESTION_CHARS = 500;
export const MAX_HISTORY_ITEMS = 6;
export const MAX_HISTORY_TEXT_CHARS = 2000;

/** Số ký tự như server đếm: chuẩn hóa NFC, đếm theo ký tự Unicode (không phải byte, không UTF-16). */
export function countChars(text: string): number {
  return [...text.normalize("NFC")].length;
}

/** Lỗi kiểm tra phía web trước khi gửi (cùng luật với lỗi 400 của server); null = hợp lệ. */
export function questionProblem(question: string): string | null {
  const trimmed = question.trim();
  if (!trimmed) return "Bạn chưa nhập câu hỏi.";
  if (countChars(trimmed) > MAX_QUESTION_CHARS) {
    return `Câu hỏi dài quá ${MAX_QUESTION_CHARS} ký tự, bạn rút gọn giúp.`;
  }
  return null;
}

/** Một lượt hỏi đáp đã có câu trả lời (lượt lỗi không đưa vào lịch sử). */
export interface CompletedTurn {
  question: string;
  answer: string;
}

/**
 * Lịch sử gửi lên: tối đa 3 lượt gần nhất (6 phần tử), từ cũ đến mới, user/assistant xen kẽ.
 * Server không tự cắt mà báo invalid_history, nên lượt có câu nào dài quá 2000 ký tự thì dừng ở đó
 * (bỏ lượt đó và các lượt cũ hơn) thay vì cắt chữ.
 */
export function buildHistory(turns: readonly CompletedTurn[]): ChatHistoryItem[] {
  const kept: CompletedTurn[] = [];
  for (let i = turns.length - 1; i >= 0 && kept.length < MAX_HISTORY_ITEMS / 2; i -= 1) {
    const { question, answer } = turns[i];
    // Cùng luật với server: text.strip() không rỗng và tối đa 2000 ký tự
    const fits = (t: string) => t.trim().length > 0 && countChars(t) <= MAX_HISTORY_TEXT_CHARS;
    if (!fits(question) || !fits(answer)) break;
    kept.unshift(turns[i]);
  }
  return kept.flatMap(({ question, answer }) => [
    { role: "user" as const, text: question },
    { role: "assistant" as const, text: answer },
  ]);
}

export function postChat(
  asset: AssetId,
  question: string,
  turns: readonly CompletedTurn[],
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const history = buildHistory(turns);
  return apiPost<ChatResponse>(
    "/chat",
    {
      question: question.trim(),
      context: { asset, page: "product" },
      ...(history.length ? { history } : {}),
    },
    signal,
  );
}

/** Link trích dẫn: chỉ nhận http/https (contract mục "Bảo mật"); khác → null, hiển thị không link. */
export function safeLink(link: string): string | null {
  try {
    const url = new URL(link);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

export function citationLinks(citations: readonly ChatCitation[]) {
  return citations.map((c) => ({ ...c, href: safeLink(c.link) }));
}

const VN_PARTS = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Ho_Chi_Minh",
  hour: "2-digit",
  minute: "2-digit",
  day: "2-digit",
  month: "2-digit",
  hourCycle: "h23",
});

/** "2026-11-03T17:00:00Z" → "00:00 ngày 04/11" (giờ Việt Nam); chuỗi sai dạng → null. */
export function formatResetVn(iso: unknown): string | null {
  if (typeof iso !== "string") return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const parts = VN_PARTS.formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("hour")}:${part("minute")} ngày ${part("day")}/${part("month")}`;
}

/** Hết lượt trong ngày (429 rate_limited do Lambda trả, không phải throttling của stage). */
export function isRateLimited(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 429 && error.code === "rate_limited";
}

/** Câu báo lỗi cho người dùng, theo bảng lỗi của contract. */
export function chatErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "Không kết nối được tới máy chủ, bạn thử lại sau.";
  if (error.status === 429) {
    // Hai loại 429: hết lượt trong ngày (Lambda, có "error") và throttling của stage (API Gateway).
    if (error.code !== "rate_limited") return "Bạn đã hỏi quá nhiều, thử lại sau.";
    const base =
      typeof error.body.message === "string" ? error.body.message : "Bạn đã hết lượt hỏi hôm nay.";
    const resetAt = formatResetVn(error.body.reset_at);
    return resetAt ? `${base} Lượt hỏi được làm mới lúc ${resetAt} (giờ Việt Nam).` : base;
  }
  if (error.status === 504) return "Chatbot trả lời quá lâu, bạn thử hỏi ngắn hơn hoặc thử lại sau.";
  if (error.status === 503) return "Chatbot đang bận, bạn thử lại sau khoảng 10 giây.";
  // 400 (Lambda có message tiếng Việt), 401 (client đã đổi câu), 500 và lỗi khác
  return error.message;
}
