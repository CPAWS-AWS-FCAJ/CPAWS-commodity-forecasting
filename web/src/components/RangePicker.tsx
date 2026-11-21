import { useId } from "react";
import type { HistoryRange } from "../lib/priceOverview";
import { isRangeAvailable, pointsNeeded, rangeUnavailableReason } from "../lib/priceOverview";

interface Props {
  ranges: readonly HistoryRange[];
  /** Mốc đang chọn; null khi chưa mốc nào đủ dữ liệu. */
  value: HistoryRange["id"] | null;
  /** Số giá cuối phiên đang có (độ dài `price_history`). */
  pointCount: number;
  onChange: (range: HistoryRange) => void;
  label?: string;
}

/**
 * Chọn mốc xem lịch sử giá. Mốc vượt dữ liệu vẫn hiện nhưng tắt (aria-disabled, vẫn focus được để đọc
 * lý do), kèm dòng giải thích bên dưới: không ẩn im lặng.
 */
export function RangePicker({ ranges, value, pointCount, onChange, label = "Khoảng thời gian" }: Props) {
  const noteId = useId();
  const unavailable = ranges.filter((range) => !isRangeAvailable(range, pointCount));

  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      <div role="group" aria-label={label} className="inline-flex flex-wrap rounded-md border border-line bg-surface p-0.5">
        {ranges.map((range) => {
          const available = isRangeAvailable(range, pointCount);
          const active = available && range.id === value;
          return (
            <button
              key={range.id}
              type="button"
              aria-pressed={active}
              aria-disabled={available ? undefined : true}
              aria-describedby={available ? undefined : noteId}
              title={available ? `${range.sessions} phiên gần nhất` : rangeUnavailableReason(range, pointCount)}
              onClick={() => {
                if (available) onChange(range);
              }}
              className={`rounded px-3 py-1.5 text-sm transition-colors ${
                active
                  ? "bg-price text-on-price"
                  : available
                    ? "text-price hover:bg-surface-muted"
                    : "cursor-not-allowed text-muted opacity-60"
              }`}
            >
              {range.label}
            </button>
          );
        })}
      </div>
      {unavailable.length ? (
        <p id={noteId} className="text-xs text-muted sm:text-right">
          {unavailable.map((range) => range.label).join(", ")}: chưa đủ dữ liệu (cần từ{" "}
          {pointsNeeded(unavailable[0])} giá cuối phiên, hiện có {pointCount}).
        </p>
      ) : null}
    </div>
  );
}
