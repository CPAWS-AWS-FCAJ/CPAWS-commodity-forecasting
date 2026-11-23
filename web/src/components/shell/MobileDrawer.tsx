import { useEffect, useRef } from "react";
import type { ReactNode, RefObject } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface Props {
  id: string;
  open: boolean;
  onClose: () => void;
  /** Nút mở menu: nhận lại focus khi đóng. */
  returnFocusRef: RefObject<HTMLElement | null>;
  label: string;
  children: ReactNode;
}

/**
 * Hành vi hộp thoại dùng chung (ngăn kéo menu, ngăn chatbot trên điện thoại): khi mở thì focus vào
 * phần tử có data-autofocus (hoặc phần tử đầu tiên), giữ Tab trong panel, Esc để đóng, khóa cuộn trang
 * nền; khi đóng thì trả focus về nút đã mở.
 */
export function useDialogBehavior(
  panelRef: RefObject<HTMLElement | null>,
  open: boolean,
  onClose: () => void,
  returnFocusRef: RefObject<HTMLElement | null>,
) {
  const wasOpen = useRef(false);

  useEffect(() => {
    if (!open) {
      if (wasOpen.current) returnFocusRef.current?.focus();
      wasOpen.current = false;
      return;
    }
    wasOpen.current = true;
    const panel = panelRef.current;
    // Ưu tiên phần tử đánh dấu data-autofocus (nút Đóng), không thì phần tử đầu tiên.
    (panel?.querySelector<HTMLElement>("[data-autofocus]") ?? panel?.querySelector<HTMLElement>(FOCUSABLE))?.focus();

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !panel.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !panel.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose, returnFocusRef, panelRef]);
}

/**
 * Ngăn kéo menu trên mobile (dưới lg): trượt từ trái, đóng bằng Esc hoặc bấm ra ngoài, giữ focus bên
 * trong khi mở, trả focus về nút mở khi đóng, khóa cuộn trang nền (useDialogBehavior). Đóng thì `inert`
 * để không Tab vào.
 */
export function MobileDrawer({ id, open, onClose, returnFocusRef, label, children }: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  useDialogBehavior(panelRef, open, onClose, returnFocusRef);

  return (
    <div
      className={`fixed inset-0 z-40 lg:hidden ${open ? "" : "pointer-events-none"}`}
      aria-hidden={!open}
      inert={!open}
    >
      <div
        data-testid="drawer-backdrop"
        onClick={onClose}
        className={`absolute inset-0 bg-canvas/80 transition-opacity ease-standard motion-reduce:transition-none ${
          open ? "duration-300" : "duration-200"
        } ${
          open ? "opacity-100" : "opacity-0"
        }`}
      />
      <div
        id={id}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        // Mở 300ms (đường cong vào), đóng 200ms: đóng nhanh hơn mở để không cản thao tác tiếp theo
        className={`absolute inset-y-0 left-0 flex w-72 max-w-[85%] flex-col border-r border-line bg-surface transition-transform motion-reduce:transition-none ${
          open ? "translate-x-0 duration-300 ease-enter" : "-translate-x-full duration-200 ease-exit"
        }`}
      >
        {children}
      </div>
    </div>
  );
}
