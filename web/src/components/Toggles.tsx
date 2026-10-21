import type { Currency } from "../api/types";
import type { Mode } from "../lib/settings";

interface SegmentedProps<T extends string> {
  label: string;
  value: T;
  options: { value: T; text: string }[];
  onChange: (value: T) => void;
}

function Segmented<T extends string>({ label, value, options, onChange }: SegmentedProps<T>) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-md border border-line bg-white p-0.5">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={`rounded px-3 py-1.5 text-sm ${
              active ? "bg-price text-white" : "text-price hover:bg-canvas"
            }`}
          >
            {option.text}
          </button>
        );
      })}
    </div>
  );
}

export function ModeToggle({ value, onChange }: { value: Mode; onChange: (mode: Mode) => void }) {
  return (
    <Segmented
      label="Chế độ hiển thị"
      value={value}
      onChange={onChange}
      options={[
        { value: "basic", text: "Cơ bản" },
        { value: "advanced", text: "Nâng cao" },
      ]}
    />
  );
}

export function CurrencyToggle({
  value,
  onChange,
}: {
  value: Currency;
  onChange: (currency: Currency) => void;
}) {
  return (
    <Segmented
      label="Đơn vị tiền"
      value={value}
      onChange={onChange}
      options={[
        { value: "USD", text: "USD" },
        { value: "VND", text: "VND" },
      ]}
    />
  );
}

/** Chọn chân trời 1 / 3 / 7 ngày bằng nút, không dùng thanh trượt. */
export function HorizonPicker({
  value,
  options,
  onChange,
}: {
  value: number;
  options: readonly number[];
  onChange: (h: number) => void;
}) {
  return (
    <Segmented
      label="Chân trời dự báo"
      value={String(value)}
      onChange={(next) => onChange(Number(next))}
      options={options.map((h) => ({ value: String(h), text: `${h} ngày` }))}
    />
  );
}
