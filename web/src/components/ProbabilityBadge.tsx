import { describeProbability } from "../lib/forecast";
import type { Lean } from "../lib/forecast";
import { Swap } from "./Swap";

const ARROW: Record<Lean, string> = { up: "▲", down: "▼", flat: "◆" };
const COLOR: Record<Lean, string> = { up: "text-up", down: "text-down", flat: "text-muted" };
const FILL: Record<Lean, string> = { up: "bg-up", down: "bg-down", flat: "bg-muted" };

interface Props {
  /** `prob_up` của API cho đúng mức h đang hiển thị. */
  probUp: number;
  horizonDays: number;
}

/**
 * Nhãn hướng kèm kỳ hạn + xác suất tăng + thanh 0–100% có vạch 50% (không chỉ dựa vào màu).
 * Mũi tên và màu theo cùng ngưỡng 60/40 với nhãn.
 */
export function ProbabilityBadge({ probUp, horizonDays }: Props) {
  const text = describeProbability(probUp);
  return (
    <div>
      <p className={`text-lg font-semibold transition-colors duration-200 ${COLOR[text.lean]}`}>
        <Swap value={`${text.label}-${horizonDays}`}>
          <span aria-hidden="true">{ARROW[text.lean]} </span>
          {text.label}{" "}
          <span className="whitespace-nowrap text-sm font-normal text-muted">· {horizonDays} phiên</span>
        </Swap>
      </p>
      <div
        role="meter"
        aria-label="Xác suất giá tăng"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={text.barPercent}
        aria-valuetext={`Xác suất tăng ${text.probUpLabel}`}
        className="relative mt-2 h-2 rounded-full bg-line"
      >
        {/* Thanh dài theo scaleX (không đổi width): đổi số phiên thì thanh trượt tới mức mới */}
        <div
          className={`h-2 origin-left rounded-full transition-[transform,background-color] duration-300 ease-standard ${FILL[text.lean]}`}
          style={{ transform: `scaleX(${text.barPercent / 100})` }}
        />
        <div className="absolute inset-y-[-3px] left-1/2 w-px bg-price" aria-hidden="true" />
      </div>
      <p className="mt-1 text-xs text-muted">
        <Swap value={text.probUpLabel}>Xác suất giá tăng: {text.probUpLabel} (vạch giữa = 50%)</Swap>
      </p>
    </div>
  );
}
