import { Link, useLocation } from "react-router-dom";
import { config } from "../../api/config";
import { displayName, useAuth } from "../../auth/AuthContext";
import { SIGN_IN_PATH, signInPath } from "../../auth/redirect";
import SignOutButton from "../../auth/SignOutButton";
import { SignInIcon, UserPlusIcon } from "./icons";
import { ThemeToggle } from "./ThemeToggle";

/** Ô vuông chỉ có icon trong dải hẹp (sidebar desktop thu gọn). */
const RAIL_SQUARE = "mx-auto flex size-10 items-center justify-center rounded-md transition-colors duration-150";

/**
 * Cuối sidebar: khối tài khoản (Họ tên, tài khoản cũ chưa có tên thì hiện email), công tắc giao diện
 * tối, nút Đăng xuất. Chưa đăng nhập: nút Đăng nhập (và Tạo tài khoản nếu pool cho tự đăng ký).
 */
export function AccountBlock({ onNavigate, collapsed = false }: { onNavigate?: () => void; collapsed?: boolean }) {
  const { status, sampleMode, account } = useAuth();
  const location = useLocation();
  // Đang ở trang đăng nhập (ngăn kéo của trang công khai): giữ `next` cũ thay vì trỏ về chính nó.
  const here =
    location.pathname === SIGN_IN_PATH
      ? (new URLSearchParams(location.search).get("next") ?? "/")
      : `${location.pathname}${location.search}`;

  if (collapsed) {
    return <CollapsedAccount here={here} onNavigate={onNavigate} />;
  }

  let identity;
  if (sampleMode) {
    identity = (
      <div className="px-3 py-2">
        <p className="text-sm font-medium text-price">Chế độ dữ liệu mẫu</p>
        <p className="mt-0.5 text-xs text-muted">Không cần đăng nhập khi chạy thử</p>
      </div>
    );
  } else if (status === "authenticated") {
    const name = displayName(account);
    // Dòng phụ: email khi dòng chính đã là Họ tên (không lặp lại email hai lần).
    const email = account?.email?.trim();
    const secondary = email && email !== name ? email : null;
    identity = (
      <div className="flex items-center gap-2.5 px-3 py-2">
        <span
          aria-hidden="true"
          className="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-muted text-sm font-medium text-price ring-1 ring-inset ring-line"
        >
          {name ? name.charAt(0).toLocaleUpperCase("vi-VN") : ""}
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-price" title={name ?? undefined}>
            {name ?? "Đang tải tài khoản…"}
          </p>
          {secondary ? <p className="truncate text-xs text-muted">{secondary}</p> : null}
        </div>
      </div>
    );
  } else if (status === "unauthenticated") {
    identity = (
      <div className="grid gap-2 px-1 py-1">
        <Link
          to={signInPath(here)}
          onClick={onNavigate}
          className="inline-flex h-9 items-center justify-center rounded-md bg-price pointer-coarse:h-11 px-3 text-sm font-medium text-on-price transition-opacity duration-150 hover:opacity-90 active:opacity-80"
        >
          Đăng nhập
        </Link>
        {config.allowSignUp ? (
          <Link
            to={signInPath(here, { signUp: true })}
            onClick={onNavigate}
            className="inline-flex h-9 items-center justify-center rounded-md pointer-coarse:h-11 border border-line bg-surface px-3 text-sm text-price transition-colors duration-150 hover:bg-surface-muted active:bg-line"
          >
            Tạo tài khoản
          </Link>
        ) : null}
      </div>
    );
  } else {
    identity = <p className="px-3 py-2 text-sm text-muted">Đang kiểm tra đăng nhập…</p>;
  }

  return (
    <div className="space-y-1">
      {identity}
      <ThemeToggle />
      {!sampleMode && status === "authenticated" ? <SignOutButton /> : null}
    </div>
  );
}

/**
 * Khối tài khoản trong dải hẹp: chữ cái đầu tên (tooltip Họ tên), Đăng nhập/Tạo tài khoản và Đăng xuất
 * dạng icon có aria-label + title, công tắc giao diện bản icon.
 */
function CollapsedAccount({ here, onNavigate }: { here: string; onNavigate?: () => void }) {
  const { status, sampleMode, account } = useAuth();
  let identity = null;
  if (sampleMode) {
    identity = (
      <p title="Chế độ dữ liệu mẫu, không cần đăng nhập khi chạy thử" className="text-center text-[11px] text-muted">
        Mẫu
        <span className="sr-only">: Chế độ dữ liệu mẫu</span>
      </p>
    );
  } else if (status === "authenticated") {
    const name = displayName(account);
    identity = (
      <span
        role="img"
        aria-label={name ?? "Tài khoản"}
        title={name ?? undefined}
        className="mx-auto flex size-8 items-center justify-center rounded-full bg-surface-muted text-sm font-medium text-price ring-1 ring-inset ring-line"
      >
        <span aria-hidden="true">{name ? name.charAt(0).toLocaleUpperCase("vi-VN") : ""}</span>
      </span>
    );
  } else if (status === "unauthenticated") {
    identity = (
      <>
        <Link
          to={signInPath(here)}
          onClick={onNavigate}
          aria-label="Đăng nhập"
          title="Đăng nhập"
          className={`${RAIL_SQUARE} bg-price text-on-price hover:opacity-90`}
        >
          <SignInIcon />
        </Link>
        {config.allowSignUp ? (
          <Link
            to={signInPath(here, { signUp: true })}
            onClick={onNavigate}
            aria-label="Tạo tài khoản"
            title="Tạo tài khoản"
            className={`${RAIL_SQUARE} border border-line text-price hover:bg-surface-muted`}
          >
            <UserPlusIcon />
          </Link>
        ) : null}
      </>
    );
  }

  return (
    <div className="flex flex-col items-center gap-1.5">
      {identity}
      <ThemeToggle variant="icon" />
      {!sampleMode && status === "authenticated" ? <SignOutButton compact /> : null}
    </div>
  );
}
