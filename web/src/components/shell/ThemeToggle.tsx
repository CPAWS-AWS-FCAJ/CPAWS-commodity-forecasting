import { useTheme } from "../../lib/theme";
import { MoonIcon, SunIcon } from "./icons";

/**
 * Công tắc giao diện tối (role="switch"): bản "row" trong sidebar có nhãn chữ, bản "icon" trên thanh
 * trên của mobile và trang công khai. Đổi class "dark" trên <html> qua useTheme (lib/theme.tsx).
 */
export function ThemeToggle({ variant = "row" }: { variant?: "row" | "icon" }) {
  const { theme, toggleTheme } = useTheme();
  const dark = theme === "dark";

  if (variant === "icon") {
    return (
      <button
        type="button"
        role="switch"
        aria-checked={dark}
        aria-label="Giao diện tối"
        title={dark ? "Đang dùng giao diện tối" : "Đang dùng giao diện sáng"}
        onClick={toggleTheme}
        className="inline-flex size-9 items-center justify-center rounded-md pointer-coarse:size-11 text-muted transition-colors duration-150 hover:bg-surface-muted hover:text-price active:bg-line"
      >
        {dark ? <SunIcon /> : <MoonIcon />}
      </button>
    );
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      onClick={toggleTheme}
      className="flex h-9 w-full items-center gap-2.5 pointer-coarse:h-11 rounded-md px-3 text-sm text-muted transition-colors duration-150 hover:bg-surface-muted hover:text-price active:bg-line"
    >
      <MoonIcon />
      <span className="flex-1 text-left">Giao diện tối</span>
      {/* Rãnh công tắc: chấm trượt bằng transform, tắt chuyển động khi người dùng giảm chuyển động */}
      <span
        aria-hidden="true"
        className={`relative inline-flex h-4 w-7 shrink-0 items-center rounded-full border transition-colors duration-150 ${
          dark ? "border-price bg-price" : "border-line bg-surface-muted"
        }`}
      >
        <span
          className={`absolute left-0.5 size-2.5 rounded-full transition-transform duration-150 motion-reduce:transition-none ${
            dark ? "translate-x-3 bg-on-price" : "translate-x-0 bg-muted"
          }`}
        />
      </span>
    </button>
  );
}
