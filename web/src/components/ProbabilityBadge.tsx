import { describeProbability } from "../lib/forecast";
import type { Lean } from "../lib/forecast";

const ARROW: Record<Lean, string> = { up: "▲", down: "▼", flat: "◆" };
const COLOR: Record<Lean, string> = { up: "text-up", down: "text-down", flat: "text-muted" };
const FILL: Record<Lean, string> = { up: "bg-up", down: "bg-down", flat: "bg-muted" };

interface Props {
  probUp: number;
  /** 0 nằm ngoài [q10, q90] → ghi "trên 90%" thay vì con số chính xác. */
  zeroBelowQ10?: boolean;
  zeroAboveQ90?: boolean;
  horizonDays: number;
}

/** Khả năng tăng/giảm: mũi tên + chữ + thanh 0–100% có vạch 50% (không chỉ dựa vào màu). */
export function ProbabilityBadge({
  probUp,
  zeroBelowQ10 = false,
  zeroAboveQ90 = false,
  horizonDays,
}: Props) {
  const text = describeProbability(probUp, { zeroBelowQ10, zeroAboveQ90 });
  return (
    <div>
      <p className={`text-lg font-semibold ${COLOR[text.lean]}`}>
        <span aria-hidden="true">{ARROW[text.lean]} </span>
        {text.headline}{" "}
        <span className="whitespace-nowrap text-sm font-normal text-muted">({horizonDays} ngày)</span>
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
