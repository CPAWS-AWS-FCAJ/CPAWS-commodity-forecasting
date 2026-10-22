import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { Currency } from "../api/types";

export type Mode = "basic" | "advanced";

interface Settings {
  mode: Mode;
  currency: Currency;
  setMode: (mode: Mode) => void;
  setCurrency: (currency: Currency) => void;
}

const MODE_KEY = "cpaws.mode";
const CURRENCY_KEY = "cpaws.currency";

// localStorage có thể ném lỗi (chế độ riêng tư, chặn dữ liệu site): luôn bọc try/catch.
function readStored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const value = window.localStorage.getItem(key);
    return (allowed as readonly string[]).includes(value ?? "") ? (value as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // bỏ qua: tùy chọn chỉ mất khi tải lại trang
  }
}

const SettingsContext = createContext<Settings | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<Mode>(() =>
    readStored<Mode>(MODE_KEY, ["basic", "advanced"], "basic"),
  );
  const [currency, setCurrencyState] = useState<Currency>(() =>
    readStored<Currency>(CURRENCY_KEY, ["USD", "VND"], "USD"),
  );

  const setMode = useCallback((next: Mode) => {
    setModeState(next);
    writeStored(MODE_KEY, next);
  }, []);
  const setCurrency = useCallback((next: Currency) => {
    setCurrencyState(next);
    writeStored(CURRENCY_KEY, next);
  }, []);

  const value = useMemo(
    () => ({ mode, currency, setMode, setCurrency }),
    [mode, currency, setMode, setCurrency],
  );
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings(): Settings {
  const context = useContext(SettingsContext);
  if (!context) throw new Error("useSettings phải nằm trong SettingsProvider");
  return context;
}
