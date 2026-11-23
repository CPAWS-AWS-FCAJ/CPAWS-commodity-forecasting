import {
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type RefObject,
} from "react";
import {
  chatErrorMessage,
  citationLinks,
  countChars,
  displayAnswer,
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
import { AuthContext } from "../auth/AuthContext";
import { chatStorageKey, loadChat, saveChat, type ChatEntry } from "../lib/chatHistory";
import { formatDateVn } from "../lib/format";
import { matchesMedia, REDUCED_MOTION } from "../lib/media";
import { useExitTransition } from "../lib/motion";
import { ExpandIcon } from "./shell/icons";
import { useDialogBehavior } from "./shell/MobileDrawer";
import { SampleBadge, StaleBadge } from "./StatusBadges";

/**
 * Chatbot gọi POST /chat (docs/api/contract.md). Quy tắc hiển thị (mục "Bảo mật" của contract):
 * - `answer` là văn bản thuần: render như text (React tự escape), giữ xuống dòng bằng CSS, không
 *   dangerouslySetInnerHTML, không đổi Markdown sang HTML, không tự biến URL trong answer thành link.
 *   Chỉ bỏ cặp `**` khi hiển thị (displayAnswer); history và kiểm disclaimer dùng answer gốc.
 * - Link chỉ lấy từ `citations`, chỉ http/https, mở tab mới với rel="noopener noreferrer".
 * - Hai loại 429: hết lượt trong ngày (rate_limited, kèm giờ reset) và throttling của stage.
 * Hội thoại được giữ trong phiên (sessionStorage, lib/chatHistory.ts): chuyển trang, tải lại vẫn còn;
 * đóng tab/trình duyệt hoặc đăng xuất thì mất. Lượt gửi lên server vẫn chỉ 3 lượt gần nhất (buildHistory).
 */

type Entry = ChatEntry;
type NewEntry = Entry extends infer E ? (E extends Entry ? Omit<E, "id" | "at"> : never) : never;

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

/**
 * Chủ của hội thoại đã lưu: `sub` Cognito khi đã đăng nhập, "sample" khi tắt đăng nhập (dữ liệu mẫu).
 * Chưa biết tài khoản (đang tải) → null: chưa đọc/ghi sessionStorage.
 */
function useChatOwner(): string | null {
  const auth = useContext(AuthContext);
  if (!auth) return config.authEnabled ? null : "sample";
  if (auth.sampleMode) return "sample";
  return auth.status === "authenticated" ? (auth.account?.userId ?? null) : null;
}

const nextIdAfter = (entries: readonly Entry[]) => entries.reduce((max, e) => Math.max(max, e.id + 1), 0);

function useChat(asset: AssetId, storageKey: string | null) {
  const [entries, setEntries] = useState<Entry[]>(() => (storageKey ? loadChat(storageKey) : []));
  const [loadedKey, setLoadedKey] = useState(storageKey);
  const [pending, setPending] = useState(false);
  const nextId = useRef(nextIdAfter(entries));
  const abort = useRef<AbortController | null>(null);

  // Khóa đổi (tài khoản vừa tải xong): đọc hội thoại của khóa mới. Từ "chưa biết" sang khóa thật mà đã
  // có tin nhắn thì giữ và lưu vào khóa mới.
  if (loadedKey !== storageKey) {
    setLoadedKey(storageKey);
    if (storageKey && (loadedKey !== null || entries.length === 0)) {
      const restored = loadChat(storageKey);
      nextId.current = nextIdAfter(restored);
      setEntries(restored);
    } else if (!storageKey) {
      setEntries([]);
    }
  }

  useEffect(() => {
    if (storageKey && loadedKey === storageKey) saveChat(storageKey, entries);
  }, [storageKey, loadedKey, entries]);

  // Rời trang thì hủy request đang chờ
  useEffect(() => () => abort.current?.abort(), []);

  const send = useCallback(
    async (question: string) => {
      const text = question.trim();
      if (pending || questionProblem(text)) return;
      const turns = completedTurns(entries);
      const add = (entry: NewEntry) =>
        setEntries((prev) => [...prev, { ...entry, id: nextId.current++, at: new Date().toISOString() } as Entry]);
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

/**
 * Cỡ chữ và khoảng cách theo nơi hiển thị. "regular": cột cạnh biểu đồ (từ lg chữ 15 px) và ngăn dưới
 * của điện thoại (giữ 14 px như cũ); "large": khung phóng to trên máy tính (16 px, dòng thoáng).
 */
type ChatSize = "regular" | "large";

const SIZE = {
  regular: {
    list: "p-4 text-sm lg:text-[0.9375rem] lg:leading-relaxed",
    user: "ml-8",
    assistant: "mr-6",
    small: "text-xs lg:text-[0.8125rem]",
    form: "p-3",
    rows: 2,
  },
  large: {
    list: "px-6 py-5 text-base leading-7",
    user: "ml-16",
    assistant: "mr-10",
    small: "text-sm",
    form: "px-6 py-4",
    rows: 3,
  },
} as const;

function AnswerBubble({ response, size }: { response: ChatResponse; size: ChatSize }) {
  const z = SIZE[size];
  const sample = response.forecasts_used.some((f) => f.is_sample);
  const stale = response.forecasts_used.some((f) => f.stale);
  const citations = citationLinks(response.citations);
  return (
    <div className={`${z.assistant} rounded-md bg-canvas p-3`}>
      {sample || stale ? (
        <div className="mb-2 flex flex-wrap gap-1">
          {sample ? <SampleBadge /> : null}
          {stale ? <StaleBadge /> : null}
        </div>
      ) : null}
      <p className="whitespace-pre-line break-words">{displayAnswer(response.answer)}</p>
      {response.truncated ? (
        <p className="mt-2 text-xs text-warn-fg">Câu trả lời bị cắt, hãy hỏi ngắn hơn.</p>
      ) : null}
      {citations.length ? (
        // Nguồn hiện ngay sau câu trả lời (trễ một nhịp ngắn) để mắt đọc câu trả lời trước
        <div className="mt-3 border-t border-line pt-2 motion-safe:animate-fade-in motion-safe:[animation-delay:180ms]">
          <p className="text-xs font-medium text-muted">Nguồn</p>
          <ul className={`mt-1 space-y-1 ${z.small}`}>
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

/** "Đang trả lời…" kèm ba chấm nhảy nhẹ (chỉ báo đang chờ duy nhất được lặp). */
function TypingIndicator({ size }: { size: ChatSize }) {
  return (
    <p className={`${SIZE[size].assistant} flex w-fit items-center gap-2.5 rounded-md bg-canvas px-3 py-2.5 text-muted animate-msg-in`}>
      <span aria-hidden="true" className="typing-dots inline-flex items-center gap-1 text-forecast">
        <span />
        <span />
        <span />
      </span>
      Đang trả lời…
    </p>
  );
}

/**
 * Nút "Xóa cuộc trò chuyện" có bước xác nhận nhẹ ngay tại chỗ (không dùng window.confirm): bấm lần đầu
 * hiện câu hỏi + "Xóa" / "Hủy"; Esc hoặc "Hủy" thì thôi. Xong thì focus về ô nhập.
 */
function ClearConversation({ onClear, inputRef }: { onClear: () => void; inputRef: RefObject<HTMLTextAreaElement | null> }) {
  const [confirming, setConfirming] = useState(false);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);

  useEffect(() => {
    if (confirming) cancelRef.current?.focus();
    else if (wasConfirming.current) triggerRef.current?.focus();
    wasConfirming.current = confirming;
  }, [confirming]);

  // Màn cảm ứng: vùng chạm tối thiểu 44×44 px
  const small =
    "inline-flex items-center justify-center rounded-md px-2.5 py-1 text-xs transition-colors duration-150 pointer-coarse:min-h-11 pointer-coarse:min-w-11";
  if (!confirming) {
    return (
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setConfirming(true)}
        className={`${small} text-muted hover:bg-surface-muted hover:text-price active:bg-line`}
      >
        Xóa cuộc trò chuyện
      </button>
    );
  }
  return (
    <div
      role="group"
      aria-label="Xác nhận xóa cuộc trò chuyện"
      className="flex flex-wrap items-center gap-1.5 animate-fade-in"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          // Không để Esc đóng luôn hộp thoại chứa khung chat
          event.stopPropagation();
          event.nativeEvent.stopImmediatePropagation();
          setConfirming(false);
        }
      }}
    >
      <span className="text-xs text-muted">Xóa toàn bộ cuộc trò chuyện?</span>
      <button
        type="button"
        onClick={() => {
          wasConfirming.current = false;
          setConfirming(false);
          onClear();
          inputRef.current?.focus();
        }}
        className={`${small} border border-line font-medium text-down hover:bg-down-bg`}
      >
        Xóa
      </button>
      <button
        ref={cancelRef}
        type="button"
        onClick={() => setConfirming(false)}
        className={`${small} text-muted hover:bg-surface-muted hover:text-price`}
      >
        Hủy
      </button>
    </div>
  );
}

interface DraftState {
  draft: string;
  setDraft: (value: string) => void;
}

function ChatBody({
  assetName,
  chat,
  draftState,
  size = "regular",
}: {
  assetName: string;
  chat: ChatState;
  /** Câu đang gõ giữ ở ChatPanel để chuyển cột ↔ khung phóng to không mất chữ. */
  draftState: DraftState;
  size?: ChatSize;
}) {
  const inputId = useId();
  const hintId = useId();
  const { draft, setDraft } = draftState;
  const z = SIZE[size];
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const disabled = config.useSample;
  const problem = draft.trim() ? questionProblem(draft) : null;
  const chars = countChars(draft.trim());
  const resetText = formatResetVn(chat.quota?.resetAt);
  // Tin nhắn đã có khi khung này mở (khôi phục từ phiên, chuyển cột ↔ khung lớn) không chạy hiệu ứng lại
  const [shownAtMount] = useState(() => new Set(chat.entries.map((e) => e.id)));
  const scrolledOnce = useRef(false);

  useEffect(() => {
    // Chỉ cuộn khung danh sách tin (không kéo cả trang như scrollIntoView). Lần đầu (mở khung, khôi
    // phục hội thoại) nhảy thẳng xuống cuối; sau đó cuộn mượt tới tin mới.
    const list = listRef.current;
    if (!list) return;
    const smooth = scrolledOnce.current && !matchesMedia(REDUCED_MOTION);
    scrolledOnce.current = true;
    if (typeof list.scrollTo === "function") {
      list.scrollTo({ top: list.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    } else {
      list.scrollTop = list.scrollHeight;
    }
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

  const enter = (id: number) => (shownAtMount.has(id) ? "" : " animate-msg-in");

  return (
    <div className="flex h-full flex-col">
      <div ref={listRef} className={`flex-1 space-y-3 overflow-y-auto overscroll-contain ${z.list}`} aria-live="polite">
        {chat.entries.length === 0 ? (
          <p className="rounded-md bg-canvas p-3 text-muted">
            {disabled
              ? "Bản xem thử đang dùng dữ liệu mẫu nên chatbot tạm tắt."
              : `Hỏi bằng tiếng Việt về dự báo ${assetName}: khả năng tăng hay giảm, khoảng dự báo, tin tức gần đây. Số liệu lấy từ hệ thống, tin có trích nguồn.`}
          </p>
        ) : null}
        {chat.entries.map((entry) =>
          entry.kind === "user" ? (
            <p
              key={entry.id}
              className={`${z.user} whitespace-pre-line break-words rounded-md bg-price p-3 text-on-price${enter(entry.id)}`}
            >
              {entry.text}
            </p>
          ) : entry.kind === "assistant" ? (
            <div key={entry.id} className={enter(entry.id).trim() || undefined}>
              <AnswerBubble response={entry.response} size={size} />
            </div>
          ) : (
            <p
              key={entry.id}
              role="alert"
              className={`${z.assistant} rounded-md bg-warn-bg p-3 text-warn-fg${enter(entry.id)}`}
            >
              {entry.text}
            </p>
          ),
        )}
        {chat.pending ? <TypingIndicator size={size} /> : null}
      </div>
      <form className={`shrink-0 border-t border-line ${z.form}`} onSubmit={submit} aria-label={`Hỏi chatbot về ${assetName}`}>
        <label htmlFor={inputId} className="sr-only">
          Câu hỏi cho chatbot
        </label>
        <textarea
          ref={inputRef}
          id={inputId}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
          rows={z.rows}
          maxLength={MAX_QUESTION_CHARS * 2}
          aria-describedby={hintId}
          aria-invalid={problem ? true : undefined}
          placeholder={disabled ? "Chatbot tạm tắt" : "Ví dụ: Phiên tới có khả năng tăng không?"}
          className={`w-full resize-none rounded-md border border-line bg-canvas p-2.5 text-base transition-[border-color,box-shadow] duration-150 focus:border-forecast ${
            size === "large" ? "leading-7" : "lg:min-h-24 lg:text-[0.9375rem] lg:leading-relaxed"
          }`}
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
        <div className="mt-2">
          <button
            type="submit"
            disabled={disabled || chat.pending || !draft.trim() || Boolean(problem)}
            className="press w-full rounded-md bg-price px-3 py-2 text-sm text-on-price hover:opacity-90 disabled:opacity-50 pointer-coarse:min-h-11"
          >
            {chat.pending ? "Đang gửi…" : "Gửi"}
          </button>
        </div>
        {resetText ? (
          <p className="mt-1 text-xs text-muted">Lượt hỏi làm mới lúc {resetText} (giờ Việt Nam).</p>
        ) : null}
        {disabled ? null : (
          <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
            <p className="text-xs text-muted">Cuộc trò chuyện được giữ đến khi bạn đóng trang.</p>
            {chat.entries.length ? <ClearConversation onClear={chat.clear} inputRef={inputRef} /> : null}
          </div>
        )}
      </form>
    </div>
  );
}

/** Từ lg trở lên (máy tính): khung phóng to chỉ dùng ở đây; nhỏ hơn đã có ngăn toàn màn hình. */
const DESKTOP_QUERY = "(min-width: 64rem)";

/**
 * Máy tính: cột bên cạnh biểu đồ, cao gần hết màn hình và dính khi cuộn (AssetPage đặt sticky), có nút
 * "Phóng to" mở hộp thoại rộng ~46rem, chữ 16 px. Điện thoại: ngăn dưới màn hình (sheet) cao theo `dvh`,
 * chừa vùng an toàn; màn thấp (điện thoại nằm ngang) thì chiếm cả màn hình. Sheet và khung phóng to là
 * hộp thoại thật: focus vào nút đóng khi mở, giữ Tab bên trong, Esc để đóng, khóa cuộn trang nền, đóng
 * thì trả focus về nút mở (useDialogBehavior, dùng chung với ngăn kéo menu). Mọi nơi dùng chung một hội
 * thoại và một câu đang gõ (state ở đây). AssetPage gắn key theo tài sản nên đổi trang tài sản thì hội
 * thoại mới. Ô nhập 16 px dưới lg để Safari iOS không tự phóng to trang khi chạm vào.
 */
export function ChatPanel({ asset, assetName }: { asset: AssetId; assetName: string }) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState("");
  const draftState = { draft, setDraft };
  const owner = useChatOwner();
  const chat = useChat(asset, owner ? chatStorageKey(owner, asset) : null);
  const openButtonRef = useRef<HTMLButtonElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const expandButtonRef = useRef<HTMLButtonElement>(null);
  const expandedRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  const collapse = useCallback(() => setExpanded(false), []);
  useDialogBehavior(sheetRef, open, close, openButtonRef);
  useDialogBehavior(expandedRef, expanded, collapse, expandButtonRef);
  // Giữ hộp thoại thêm một nhịp khi đóng để trượt/thu nhỏ ra (không có ở test jsdom, giảm chuyển động)
  const sheet = useExitTransition(open, 200);
  const big = useExitTransition(expanded, 150);

  // Thu cửa sổ xuống dưới lg khi đang phóng to: đóng khung lớn (điện thoại dùng ngăn dưới)
  useEffect(() => {
    if (!expanded || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(DESKTOP_QUERY);
    const onChange = () => {
      if (!query.matches) setExpanded(false);
    };
    query.addEventListener?.("change", onChange);
    return () => query.removeEventListener?.("change", onChange);
  }, [expanded]);

  return (
    <>
      <aside
        aria-label={`Chatbot ${assetName}`}
        className="hidden h-[calc(100dvh-2rem)] min-h-[30rem] flex-col overflow-hidden rounded-lg border border-line bg-surface lg:flex"
      >
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line py-1.5 pl-4 pr-1.5">
          <h2 className="text-sm font-semibold">Hỏi chatbot về {assetName}</h2>
          <button
            ref={expandButtonRef}
            type="button"
            onClick={() => setExpanded(true)}
            aria-haspopup="dialog"
            aria-expanded={expanded}
            // Biểu đồ cũng có nút "Phóng to": tên đầy đủ để trình đọc màn hình phân biệt
            aria-label="Phóng to khung chat"
            title="Phóng to khung chat"
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-sm text-muted transition-colors duration-150 hover:bg-surface-muted hover:text-price active:bg-line"
          >
            <ExpandIcon />
            Phóng to
          </button>
        </div>
        <div className="min-h-0 flex-1">
          {expanded ? (
            <p className="p-4 text-sm text-muted animate-fade-in">Hội thoại đang mở ở khung lớn.</p>
          ) : (
            <ChatBody assetName={assetName} chat={chat} draftState={draftState} />
          )}
        </div>
      </aside>

      {big.mounted ? (
        <div
          data-motion={big.closing ? "closing" : "open"}
          inert={big.closing}
          className="fixed inset-0 z-40 hidden items-center justify-center p-6 lg:flex"
        >
          <div
            data-testid="chat-expanded-backdrop"
            aria-hidden="true"
            onClick={collapse}
            className="motion-backdrop absolute inset-0 bg-canvas/80 animate-fade-in"
          />
          <div
            ref={expandedRef}
            role="dialog"
            aria-modal="true"
            aria-label={`Chatbot ${assetName}, khung lớn`}
            className="motion-dialog relative flex h-[min(60rem,calc(100dvh-3rem))] w-full max-w-[46rem] flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-lg animate-scale-in"
          >
            <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line py-2 pl-6 pr-2">
              <h2 className="text-base font-semibold">Hỏi chatbot về {assetName}</h2>
              <button
                type="button"
                data-autofocus
                onClick={collapse}
                className="inline-flex h-9 items-center rounded-md px-3 text-sm text-muted transition-colors duration-150 hover:bg-surface-muted hover:text-price active:bg-line"
              >
                Thu nhỏ
              </button>
            </div>
            <div className="min-h-0 flex-1">
              <ChatBody assetName={assetName} chat={chat} draftState={draftState} size="large" />
            </div>
          </div>
        </div>
      ) : null}

      <div className="lg:hidden">
        {/* Chừa chỗ dưới footer (gắn vào cuối body) để nút nổi không che dòng disclaimer khi cuộn hết */}
        {createPortal(
          <div aria-hidden="true" className="h-[calc(5rem+env(safe-area-inset-bottom))] lg:hidden" />,
          document.body,
        )}
        <button
          ref={openButtonRef}
          type="button"
          onClick={() => setOpen(true)}
          aria-haspopup="dialog"
          className="press fixed bottom-[calc(1rem+env(safe-area-inset-bottom))] right-4 z-20 min-h-11 rounded-full bg-forecast px-4 py-3 text-sm font-medium text-on-price shadow-lg animate-scale-in"
        >
          Hỏi chatbot
        </button>
        {sheet.mounted ? (
          <div data-motion={sheet.closing ? "closing" : "open"} inert={sheet.closing} className="fixed inset-0 z-30">
            <div
              data-testid="chat-backdrop"
              aria-hidden="true"
              onClick={close}
              className="motion-backdrop absolute inset-0 bg-canvas/80 animate-fade-in"
            />
            <div
              ref={sheetRef}
              role="dialog"
              aria-modal="true"
              aria-label={`Chatbot ${assetName}`}
              className="motion-sheet absolute inset-x-0 bottom-0 flex h-[85dvh] max-h-dvh flex-col overflow-hidden rounded-t-xl border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] animate-sheet-up [@media(max-height:32rem)]:h-dvh [@media(max-height:32rem)]:rounded-none"
            >
              <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line py-1 pl-4 pr-1">
                <h2 className="text-sm font-semibold">
                  Hỏi chatbot về {assetName}
                </h2>
                <button
                  type="button"
                  data-autofocus
                  onClick={close}
                  className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md px-3 text-sm text-muted transition-colors duration-150 hover:bg-surface-muted hover:text-price"
                >
                  Đóng
                </button>
              </div>
              <div className="min-h-0 flex-1">
                <ChatBody assetName={assetName} chat={chat} draftState={draftState} />
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </>
  );
}
