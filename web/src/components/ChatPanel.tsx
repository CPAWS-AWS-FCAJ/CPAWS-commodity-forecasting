import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import {
  chatErrorMessage,
  citationLinks,
  countChars,
  formatResetVn,
  isRateLimited,
  MAX_QUESTION_CHARS,
  postChat,
  questionProblem,
  type CompletedTurn,
} from "../api/chat";
import { createPortal } from "react-dom";
import { config } from "../api/config";
import type { AssetId, ChatResponse } from "../api/types";
import { formatDateVn } from "../lib/format";
import { SampleBadge, StaleBadge } from "./StatusBadges";

/**
 * Chatbot gọi POST /chat (docs/api/contract.md). Quy tắc hiển thị (mục "Bảo mật" của contract):
 * - `answer` là văn bản thuần: render như text (React tự escape), giữ xuống dòng bằng CSS, không
 *   dangerouslySetInnerHTML, không đổi Markdown sang HTML, không tự biến URL trong answer thành link.
 * - Link chỉ lấy từ `citations`, chỉ http/https, mở tab mới với rel="noopener noreferrer".
 * - Hai loại 429: hết lượt trong ngày (rate_limited, kèm giờ reset) và throttling của stage.
 */

type Entry =
  | { id: number; kind: "user"; text: string }
  | { id: number; kind: "assistant"; response: ChatResponse }
  | { id: number; kind: "error"; text: string; resetAt?: string };
type NewEntry = Entry extends infer E ? (E extends Entry ? Omit<E, "id"> : never) : never;

/** Lượt đã có câu trả lời (không bị chặn) → đưa vào history gửi lên. */
function completedTurns(entries: readonly Entry[]): CompletedTurn[] {
  const turns: CompletedTurn[] = [];
  entries.forEach((entry, i) => {
    const prev = entries[i - 1];
    if (entry.kind === "assistant" && !entry.response.blocked && prev?.kind === "user") {
      turns.push({ question: prev.text, answer: entry.response.answer });
    }
  });
  return turns;
}

function useChat(asset: AssetId) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [pending, setPending] = useState(false);
  const nextId = useRef(0);
  const abort = useRef<AbortController | null>(null);

  // Rời trang thì hủy request đang chờ
  useEffect(() => () => abort.current?.abort(), []);

  const send = useCallback(
    async (question: string) => {
      const text = question.trim();
      if (pending || questionProblem(text)) return;
      const turns = completedTurns(entries);
      const add = (entry: NewEntry) =>
        setEntries((prev) => [...prev, { ...entry, id: nextId.current++ } as Entry]);
      add({ kind: "user", text });
      setPending(true);
      const controller = new AbortController();
      abort.current = controller;
      try {
        const response = await postChat(asset, text, turns, controller.signal);
        add({ kind: "assistant", response });
      } catch (error) {
        if (controller.signal.aborted) return;
        const resetAt =
          isRateLimited(error) && typeof error.body.reset_at === "string" ? error.body.reset_at : undefined;
        add({ kind: "error", text: chatErrorMessage(error), ...(isRateLimited(error) ? { resetAt } : {}) });
      } finally {
        if (!controller.signal.aborted) setPending(false);
      }
    },
    [asset, entries, pending],
  );

  const clear = useCallback(() => {
    abort.current?.abort();
    setPending(false);
    setEntries([]);
  }, []);

  return { entries, pending, send, clear, quota: quotaState(entries) };
}

interface QuotaView {
  /** null khi hết lượt sau 429 rate_limited (không còn số chính xác từ server) */
  remaining: number | null;
  limit: number | null;
  resetAt: string | undefined;
  exhausted: boolean;
}

/**
 * Số lượt lấy từ câu trả lời thành công gần nhất; nếu sau đó gặp 429 rate_limited thì coi như hết
 * lượt (không hiện số cũ "Còn x/20").
 */
function quotaState(entries: readonly Entry[]): QuotaView | null {
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    const e = entries[i];
    if (e.kind === "assistant" && e.response.quota) {
      const q = e.response.quota;
      return { remaining: q.remaining, limit: q.limit, resetAt: q.reset_at, exhausted: q.remaining <= 0 };
    }
    if (e.kind === "error" && "resetAt" in e) {
      return { remaining: null, limit: null, resetAt: e.resetAt, exhausted: true };
    }
  }
  return null;
}

type ChatState = ReturnType<typeof useChat>;

function AnswerBubble({ response }: { response: ChatResponse }) {
  const sample = response.forecasts_used.some((f) => f.is_sample);
  const stale = response.forecasts_used.some((f) => f.stale);
  const citations = citationLinks(response.citations);
  return (
    <div className="mr-6 rounded-md bg-canvas p-3">
      {sample || stale ? (
        <div className="mb-2 flex flex-wrap gap-1">
          {sample ? <SampleBadge /> : null}
          {stale ? <StaleBadge /> : null}
        </div>
      ) : null}
      <p className="whitespace-pre-line break-words">{response.answer}</p>
      {response.truncated ? (
        <p className="mt-2 text-xs text-warn-fg">Câu trả lời bị cắt, hãy hỏi ngắn hơn.</p>
      ) : null}
      {citations.length ? (
        <div className="mt-3 border-t border-line pt-2">
          <p className="text-xs font-medium text-muted">Nguồn</p>
          <ul className="mt-1 space-y-1 text-xs">
            {citations.map((c, i) => (
              <li key={`${c.link}-${i}`}>
                {c.href ? (
                  <a
                    href={c.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-forecast underline underline-offset-2"
                  >
                    {c.title}
                  </a>
                ) : (
                  <span>{c.title}</span>
                )}
                <span className="text-muted">
                  {" "}
                  · {c.source} · {formatDateVn(c.published_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {response.answer.includes(response.disclaimer) ? null : (
        <p className="mt-2 text-xs text-muted">{response.disclaimer}</p>
      )}
      {/* Để tra log CloudWatch khi câu trả lời sai (kịch bản demo #77 mục 7); không nhạy cảm */}
      {response.request_id ? (
        <p className="mt-2 break-all text-[11px] text-muted">Mã tra cứu: {response.request_id}</p>
      ) : null}
    </div>
  );
}

function ChatBody({ assetName, chat }: { assetName: string; chat: ChatState }) {
  const inputId = useId();
  const hintId = useId();
  const [draft, setDraft] = useState("");
  const listEnd = useRef<HTMLDivElement>(null);
  const disabled = config.useSample;
  const problem = draft.trim() ? questionProblem(draft) : null;
  const chars = countChars(draft.trim());
  const resetText = formatResetVn(chat.quota?.resetAt);

  useEffect(() => {
    listEnd.current?.scrollIntoView?.({ block: "end" });
  }, [chat.entries.length, chat.pending]);

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (disabled || chat.pending || questionProblem(draft)) return;
    void chat.send(draft);
    setDraft("");
  };

  // Enter gửi, Shift+Enter xuống dòng
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) submit(event);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto p-4 text-sm" aria-live="polite">
        {chat.entries.length === 0 ? (
          <p className="rounded-md bg-canvas p-3 text-muted">
            {disabled
              ? "Bản xem thử đang dùng dữ liệu mẫu nên chatbot tạm tắt."
              : `Hỏi bằng tiếng Việt về dự báo ${assetName}: khả năng tăng hay giảm, khoảng dự báo, tin tức gần đây. Số liệu lấy từ hệ thống, tin có trích nguồn.`}
          </p>
        ) : null}
        {chat.entries.map((entry) =>
          entry.kind === "user" ? (
            <p key={entry.id} className="ml-6 whitespace-pre-line break-words rounded-md bg-price p-3 text-white">
              {entry.text}
            </p>
          ) : entry.kind === "assistant" ? (
            <AnswerBubble key={entry.id} response={entry.response} />
          ) : (
            <p key={entry.id} role="alert" className="mr-6 rounded-md bg-warn-bg p-3 text-warn-fg">
              {entry.text}
            </p>
          ),
        )}
        {chat.pending ? <p className="text-muted">Đang trả lời…</p> : null}
        <div ref={listEnd} />
      </div>
      <form className="border-t border-line p-3" onSubmit={submit} aria-label={`Hỏi chatbot về ${assetName}`}>
        <label htmlFor={inputId} className="sr-only">
          Câu hỏi cho chatbot
        </label>
        <textarea
          id={inputId}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
          rows={2}
          maxLength={MAX_QUESTION_CHARS * 2}
          aria-describedby={hintId}
          aria-invalid={problem ? true : undefined}
          placeholder={disabled ? "Chatbot tạm tắt" : "Ví dụ: Phiên tới có khả năng tăng không?"}
          className="w-full resize-none rounded-md border border-line bg-canvas p-2 text-sm"
        />
        <div id={hintId} className="mt-1 flex items-center justify-between gap-2 text-xs text-muted">
          <span className={problem ? "text-down" : undefined}>
            {problem ??
              (chat.quota?.exhausted
                ? "Đã hết lượt hỏi hôm nay"
                : chat.quota && chat.quota.remaining !== null
                  ? `Còn ${chat.quota.remaining}/${chat.quota.limit} lượt hôm nay`
                  : "Enter để gửi, Shift+Enter xuống dòng")}
          </span>
          <span className="tabular">
            {chars}/{MAX_QUESTION_CHARS}
          </span>
        </div>
        <div className="mt-2 flex gap-2">
          <button
            type="submit"
            disabled={disabled || chat.pending || !draft.trim() || Boolean(problem)}
            className="flex-1 rounded-md bg-price px-3 py-2 text-sm text-white disabled:opacity-50"
          >
            {chat.pending ? "Đang gửi…" : "Gửi"}
          </button>
          {chat.entries.length ? (
            <button
              type="button"
              onClick={chat.clear}
              className="rounded-md border border-line px-3 py-2 text-sm text-muted"
            >
              Xóa hội thoại
            </button>
          ) : null}
        </div>
        {resetText ? (
          <p className="mt-1 text-xs text-muted">Lượt hỏi làm mới lúc {resetText} (giờ Việt Nam).</p>
        ) : null}
      </form>
    </div>
  );
}

/**
 * Máy tính: cột bên cạnh biểu đồ. Điện thoại: ngăn kéo dưới màn hình. Hai nơi dùng chung một hội
 * thoại (state ở đây). AssetPage gắn key theo tài sản nên đổi trang tài sản thì hội thoại mới.
 */
export function ChatPanel({ asset, assetName }: { asset: AssetId; assetName: string }) {
  const [open, setOpen] = useState(false);
  const chat = useChat(asset);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <aside
        aria-label={`Chatbot ${assetName}`}
        className="hidden h-[32rem] flex-col overflow-hidden rounded-lg border border-line bg-white lg:flex"
      >
        <h2 className="border-b border-line px-4 py-3 text-sm font-semibold">Hỏi chatbot về {assetName}</h2>
        <div className="min-h-0 flex-1">
          <ChatBody assetName={assetName} chat={chat} />
        </div>
      </aside>

      <div className="lg:hidden">
        {/* Chừa chỗ dưới footer (gắn vào cuối body) để nút nổi không che dòng disclaimer khi cuộn hết */}
        {createPortal(<div aria-hidden="true" className="h-20 lg:hidden" />, document.body)}
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="fixed bottom-4 right-4 z-20 rounded-full bg-forecast px-4 py-3 text-sm font-medium text-white shadow-lg"
        >
          Hỏi chatbot
        </button>
        {open ? (
          <div role="dialog" aria-modal="true" aria-label={`Chatbot ${assetName}`} className="fixed inset-0 z-30">
            <button
              type="button"
              aria-label="Đóng chatbot"
              onClick={() => setOpen(false)}
              className="absolute inset-0 bg-black/30"
            />
            <div className="absolute inset-x-0 bottom-0 flex h-[80vh] flex-col rounded-t-xl bg-white">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <h2 className="text-sm font-semibold">Hỏi chatbot về {assetName}</h2>
                <button type="button" onClick={() => setOpen(false)} className="text-sm text-muted">
                  Đóng
                </button>
              </div>
              <div className="min-h-0 flex-1">
                <ChatBody assetName={assetName} chat={chat} />
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </>
  );
}
