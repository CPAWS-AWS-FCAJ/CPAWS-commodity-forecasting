import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { useLocation } from "react-router-dom";
import { AccountBlock } from "./AccountBlock";
import { CloseIcon, MenuIcon, SidebarToggleIcon } from "./icons";
import { MobileDrawer } from "./MobileDrawer";
import { SidebarNav } from "./SidebarNav";
import { Wordmark } from "./Wordmark";

/** id của ngăn kéo menu (nút mở trỏ tới bằng aria-controls). */
export const DRAWER_ID = "menu-dieu-huong";

/** Nút vuông trên thanh trên (menu, đóng menu): 36 px với chuột, 44 px trên màn cảm ứng. */
export const ICON_BUTTON =
  "inline-flex size-9 items-center justify-center rounded-md transition-colors duration-150 hover:bg-surface-muted active:bg-line pointer-coarse:size-11";

/** id vùng sidebar desktop (nút thu gọn trỏ tới bằng aria-controls). */
export const SIDEBAR_ID = "sidebar-dieu-huong";

interface SidebarToggle {
  collapsed: boolean;
  onToggle: () => void;
}

/** Nút thu gọn/mở sidebar desktop, ở đầu sidebar (cả khi đang là dải hẹp). */
function SidebarToggleButton({ collapsed, onToggle }: SidebarToggle) {
  const label = collapsed ? "Mở menu" : "Thu gọn menu";
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={!collapsed}
      aria-controls={SIDEBAR_ID}
      aria-label={label}
      title={label}
      className={`${ICON_BUTTON} shrink-0 text-muted hover:text-price`}
    >
      <SidebarToggleIcon collapsed={collapsed} />
    </button>
  );
}

/**
 * Nội dung dùng chung cho sidebar desktop và ngăn kéo mobile (trang trong app và trang công khai).
 * `sidebarToggle` chỉ có ở sidebar desktop: thêm nút thu gọn; khi thu gọn thì thành dải hẹp (icon,
 * chấm màu, tooltip), cùng mục và cùng ổ khóa.
 */
export function SidebarContent({
  onNavigate,
  onClose,
  sidebarToggle,
}: {
  onNavigate?: () => void;
  onClose?: () => void;
  sidebarToggle?: SidebarToggle;
}) {
  const collapsed = sidebarToggle?.collapsed ?? false;
  if (sidebarToggle && collapsed) {
    return (
      <>
        <div className="flex h-16 shrink-0 items-center justify-center">
          <SidebarToggleButton {...sidebarToggle} />
        </div>
        <nav aria-label="Điều hướng chính" className="min-h-0 flex-1 overflow-y-auto px-2 pb-4 pt-2">
          <SidebarNav collapsed onNavigate={onNavigate} />
        </nav>
        <div className="shrink-0 border-t border-line px-2 py-3">
          <AccountBlock collapsed onNavigate={onNavigate} />
        </div>
      </>
    );
  }
  return (
    <>
      <div className="flex h-16 shrink-0 items-center justify-between gap-2 px-5">
        <Wordmark onClick={onNavigate} withTagline />
        {sidebarToggle ? <SidebarToggleButton {...sidebarToggle} /> : null}
        {onClose ? (
          <button
            type="button"
            data-autofocus
            onClick={onClose}
            aria-label="Đóng menu"
            className={`${ICON_BUTTON} text-muted hover:text-price`}
          >
            <CloseIcon />
          </button>
        ) : null}
      </div>
      <nav aria-label="Điều hướng chính" className="min-h-0 flex-1 overflow-y-auto px-3 pb-6 pt-2">
        <SidebarNav onNavigate={onNavigate} />
      </nav>
      <div className="shrink-0 border-t border-line p-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]">
        <AccountBlock onNavigate={onNavigate} />
      </div>
    </>
  );
}

export interface MobileMenuState {
  open: boolean;
  show: () => void;
  close: () => void;
  buttonRef: RefObject<HTMLButtonElement | null>;
}

/** Trạng thái ngăn kéo menu; đổi trang (kể cả nút Quay lại của trình duyệt) thì đóng. */
export function useMobileMenu(): MobileMenuState {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const location = useLocation();
  const show = useCallback(() => setOpen(true), []);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  return { open, show, close, buttonRef };
}

/** Nút mở menu dưới lg (thanh trên của app và của trang công khai dùng chung). */
export function MenuButton({ menu }: { menu: MobileMenuState }) {
  return (
    <button
      ref={menu.buttonRef}
      type="button"
      onClick={menu.show}
      aria-expanded={menu.open}
      aria-controls={DRAWER_ID}
      aria-label="Mở menu"
      className={`${ICON_BUTTON} shrink-0 text-price lg:hidden`}
    >
      <MenuIcon />
    </button>
  );
}

/** Ngăn kéo menu: cùng mục, cùng ổ khóa, cùng khối tài khoản như sidebar desktop. */
export function NavDrawer({ menu }: { menu: MobileMenuState }) {
  return (
    <MobileDrawer
      id={DRAWER_ID}
      open={menu.open}
      onClose={menu.close}
      returnFocusRef={menu.buttonRef}
      label="Menu điều hướng"
    >
      <SidebarContent onNavigate={menu.close} onClose={menu.close} />
    </MobileDrawer>
  );
}
