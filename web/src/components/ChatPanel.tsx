import { useEffect, useState } from "react";

/**
 * KHUNG chatbot (chưa gọi API). POST /chat do Phước làm ở tuần 4 (demo 8/11).
 * Khi nối API: câu trả lời hiển thị dạng text đã lọc (không dangerouslySetInnerHTML),
 * link trích dẫn mở tab mới với rel="noopener noreferrer"; HTTP 429 → "Bạn đã hỏi quá nhiều, thử lại sau."
 */
function ChatBody({ assetName }: { assetName: string }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto p-4 text-sm">
        <p className="rounded-md bg-canvas p-3 text-muted">
          Chatbot tiếng Việt sẽ giải thích vì sao giá {assetName} có thể tăng hay giảm, với số liệu lấy từ
          hệ thống và tin tức có trích nguồn. Tính năng này sẽ bật ở tuần 4.
        </p>
      </div>
      <form
        className="border-t border-line p-3"
        onSubmit={(event) => event.preventDefault()}
        aria-label="Hỏi chatbot (chưa hoạt động)"
      >
        <label htmlFor="chat-input" className="sr-only">
          Câu hỏi cho chatbot
        </label>
        <textarea
          id="chat-input"
          disabled
          rows={2}
          placeholder="Chưa hoạt động"
          className="w-full resize-none rounded-md border border-line bg-canvas p-2 text-sm"
        />
        <button
          type="submit"
          disabled
          className="mt-2 w-full rounded-md bg-price px-3 py-2 text-sm text-white opacity-50"
        >
          Gửi
        </button>
      </form>
    </div>
  );
}

/** Máy tính: cột bên cạnh biểu đồ. Điện thoại: ngăn kéo dưới màn hình. */
export function ChatPanel({ assetName }: { assetName: string }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
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
          <ChatBody assetName={assetName} />
        </div>
      </aside>

      <div className="lg:hidden">
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
            <div className="absolute inset-x-0 bottom-0 flex h-[70vh] flex-col rounded-t-xl bg-white">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <h2 className="text-sm font-semibold">Hỏi chatbot về {assetName}</h2>
                <button type="button" onClick={() => setOpen(false)} className="text-sm text-muted">
                  Đóng
                </button>
              </div>
              <div className="min-h-0 flex-1">
                <ChatBody assetName={assetName} />
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </>
  );
}
