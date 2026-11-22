import { describeProbability } from "../lib/forecast";
import type { Lean } from "../lib/forecast";

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
      <p className={`text-lg font-semibold ${COLOR[text.lean]}`}>
        <span aria-hidden="true">{ARROW[text.lean]} </span>
        {text.label}{" "}
        <span className="whitespace-nowrap text-sm font-normal text-muted">· {horizonDays} phiên</span>
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
        <div className={`h-2 rounded-full ${FILL[text.lean]}`} style={{ width: `${text.barPercent}%` }} />
        <div className="absolute inset-y-[-3px] left-1/2 w-px bg-price" aria-hidden="true" />
      </div>
      <p className="mt-1 text-xs text-muted">Xác suất giá tăng: {text.probUpLabel} (vạch giữa = 50%)</p>
    </div>
  );
}
