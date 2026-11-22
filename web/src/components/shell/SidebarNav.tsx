import { useId } from "react";
import type { ComponentType, SVGProps } from "react";
import { NavLink } from "react-router-dom";
import { ASSET_IDS } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { signInPath } from "../../auth/redirect";
import { ASSET_DOT_CLASS, ASSETS } from "../../lib/assets";
import { AccuracyIcon, ForecastIcon, GuideIcon, InfoIcon, LockIcon, OverviewIcon } from "./icons";

interface Item {
  to: string;
  label: string;
  /** Cần đăng nhập (trang có dữ liệu giá, ADR-0005). */
  requiresAuth: boolean;
  end?: boolean;
  dotClass?: string;
  /** Icon cho dải hẹp khi sidebar thu gọn (mục không có chấm màu). */
  icon?: ComponentType<SVGProps<SVGSVGElement>>;
  /** Tên ngắn dưới chấm màu khi thu gọn (sản phẩm). */
  shortLabel?: string;
}

const PRIMARY: Item[] = [
  { to: "/overview", label: "Tổng quan giá", requiresAuth: true, icon: OverviewIcon },
  { to: "/", label: "Dự báo", requiresAuth: true, end: true, icon: ForecastIcon },
];

const PRODUCTS: Item[] = ASSET_IDS.map((id) => ({
  to: `/asset/${id}`,
  label: ASSETS[id].name,
  requiresAuth: true,
  dotClass: ASSET_DOT_CLASS[id],
  shortLabel: ASSETS[id].name.replace(/^Dầu /, ""),
}));

const SECONDARY: Item[] = [
  { to: "/accuracy", label: "Độ chính xác", requiresAuth: true, icon: AccuracyIcon },
  // Hướng dẫn cũng cần đăng nhập như các mục dữ liệu; chỉ Giới thiệu là công khai
  { to: "/guide", label: "Cách đọc dự báo", requiresAuth: true, icon: GuideIcon },
  { to: "/about", label: "Giới thiệu", requiresAuth: false, icon: InfoIcon },
];

const itemClass = ({ isActive }: { isActive: boolean }) =>
  `flex h-9 items-center gap-2.5 rounded-md px-3 pointer-coarse:h-11 text-sm transition-colors duration-150 ${
    isActive
      ? "bg-surface-muted font-medium text-price ring-1 ring-inset ring-line"
      : "text-muted hover:bg-surface-muted hover:text-price"
  }`;

// Dải hẹp (sidebar thu gọn): ô vuông giữa cột, tên đầy đủ ở aria-label và tooltip `title`.
const railClass = ({ isActive }: { isActive: boolean }) =>
  `relative mx-auto flex w-12 flex-col items-center justify-center gap-1 rounded-md transition-colors duration-150 ${
    isActive
      ? "bg-surface-muted text-price ring-1 ring-inset ring-line"
      : "text-muted hover:bg-surface-muted hover:text-price"
  }`;

function NavItem({
  item,
  locked,
  collapsed,
  onNavigate,
}: {
  item: Item;
  locked: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  // Chưa đăng nhập: "Dự báo" (/) là trang giới thiệu công khai, nên đưa thẳng tới đăng nhập.
  // Các trang khác cứ trỏ đúng đường dẫn; RequireAuth chuyển tới /dang-nhap?next=…
  const to = locked && item.to === "/" ? signInPath("/") : item.to;

  if (collapsed) {
    const name = locked ? `${item.label} (cần đăng nhập)` : item.label;
    const Icon = item.icon;
    return (
      <li>
        <NavLink
          to={to}
          end={item.end}
          onClick={onNavigate}
          aria-label={name}
          title={name}
          className={(state) => `${railClass(state)} ${item.dotClass ? "h-12" : "h-10"}`}
        >
          {item.dotClass ? (
            <>
              <span aria-hidden="true" className={`size-2.5 rounded-full ${item.dotClass}`} />
              <span aria-hidden="true" className="text-[11px] leading-none">
                {item.shortLabel}
              </span>
            </>
          ) : Icon ? (
            <Icon />
          ) : null}
          {locked ? (
            <LockIcon aria-hidden="true" width="10" height="10" className="absolute right-1 top-1 text-muted" />
          ) : null}
        </NavLink>
      </li>
    );
  }

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

/**
 * Ba nhóm mục: trang chính, nhóm "Sản phẩm" có chấm màu nhận diện, đánh giá và hướng dẫn.
 * `collapsed`: dải hẹp của sidebar desktop (icon, chấm màu + tên ngắn, tooltip).
 */
export function SidebarNav({ onNavigate, collapsed = false }: { onNavigate?: () => void; collapsed?: boolean }) {
  const { status } = useAuth();
  // Sidebar desktop và drawer mobile cùng render: id phải riêng cho từng bản.
  const productsId = useId();
  const signedOut = status !== "authenticated";
  const render = (items: Item[]) =>
    items.map((item) => (
      <NavItem
        key={item.to}
        item={item}
        locked={signedOut && item.requiresAuth}
        collapsed={collapsed}
        onNavigate={onNavigate}
      />
    ));

  return (
    <div className={collapsed ? "space-y-3" : "space-y-6"}>
      <ul className={collapsed ? "space-y-1" : "space-y-0.5"}>{render(PRIMARY)}</ul>
      <div className={collapsed ? "border-t border-line pt-3" : undefined}>
        <p id={productsId} className={collapsed ? "sr-only" : "px-3 pb-2 text-xs text-muted"}>
          Sản phẩm
        </p>
        <ul aria-labelledby={productsId} className={collapsed ? "space-y-1" : "space-y-0.5"}>
          {render(PRODUCTS)}
        </ul>
      </div>
      <ul className={collapsed ? "space-y-1 border-t border-line pt-3" : "space-y-0.5"}>{render(SECONDARY)}</ul>
    </div>
  );
}
