import { useId } from "react";
import { NavLink } from "react-router-dom";
import { ASSET_IDS } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { signInPath } from "../../auth/redirect";
import { ASSET_DOT_CLASS, ASSETS } from "../../lib/assets";
import { LockIcon } from "./icons";

interface Item {
  to: string;
  label: string;
  /** Cần đăng nhập (trang có dữ liệu giá, ADR-0005). */
  requiresAuth: boolean;
  end?: boolean;
  dotClass?: string;
}

const PRIMARY: Item[] = [
  { to: "/overview", label: "Tổng quan giá", requiresAuth: true },
  { to: "/", label: "Dự báo", requiresAuth: true, end: true },
];

const PRODUCTS: Item[] = ASSET_IDS.map((id) => ({
  to: `/asset/${id}`,
  label: ASSETS[id].name,
  requiresAuth: true,
  dotClass: ASSET_DOT_CLASS[id],
}));

const SECONDARY: Item[] = [
  { to: "/accuracy", label: "Độ chính xác", requiresAuth: true },
  { to: "/guide", label: "Cách đọc dự báo", requiresAuth: false },
  { to: "/about", label: "Giới thiệu", requiresAuth: false },
];

const itemClass = ({ isActive }: { isActive: boolean }) =>
  `flex h-9 items-center gap-2.5 rounded-md px-3 text-sm transition-colors duration-150 ${
    isActive
      ? "bg-surface-muted font-medium text-price ring-1 ring-inset ring-line"
      : "text-muted hover:bg-surface-muted hover:text-price"
  }`;

function NavItem({ item, locked, onNavigate }: { item: Item; locked: boolean; onNavigate?: () => void }) {
  // Chưa đăng nhập: "Dự báo" (/) là trang giới thiệu công khai, nên đưa thẳng tới đăng nhập.
  // Các trang khác cứ trỏ đúng đường dẫn; RequireAuth chuyển tới /dang-nhap?next=…
  const to = locked && item.to === "/" ? signInPath("/") : item.to;
  return (
    <li>
      <NavLink to={to} end={item.end} onClick={onNavigate} className={itemClass}>
        {item.dotClass ? (
          <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${item.dotClass}`} />
        ) : null}
        <span className="flex-1 truncate">{item.label}</span>
        {locked ? (
          <>
            <LockIcon className="text-muted" />
            <span className="sr-only">(cần đăng nhập)</span>
          </>
        ) : null}
      </NavLink>
    </li>
  );
}

/** Ba nhóm mục: trang chính, nhóm "Sản phẩm" có chấm màu nhận diện, đánh giá và hướng dẫn. */
export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const { status } = useAuth();
  // Sidebar desktop và drawer mobile cùng render: id phải riêng cho từng bản.
  const productsId = useId();
  const signedOut = status !== "authenticated";
  const render = (items: Item[]) =>
    items.map((item) => (
      <NavItem key={item.to} item={item} locked={signedOut && item.requiresAuth} onNavigate={onNavigate} />
    ));

  return (
    <div className="space-y-6">
      <ul className="space-y-0.5">{render(PRIMARY)}</ul>
      <div>
        <p id={productsId} className="px-3 pb-2 text-xs text-muted">
          Sản phẩm
        </p>
        <ul aria-labelledby={productsId} className="space-y-0.5">
          {render(PRODUCTS)}
        </ul>
      </div>
      <ul className="space-y-0.5">{render(SECONDARY)}</ul>
    </div>
  );
}
