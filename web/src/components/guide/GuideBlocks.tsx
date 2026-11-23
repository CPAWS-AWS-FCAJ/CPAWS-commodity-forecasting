import type { ReactNode } from "react";
import type { GuideAnchor } from "../HowToRead";

// Khối dựng trang "Cách đọc dự báo". Mọi minh họa là HTML/SVG tĩnh, số trong minh họa là số giả
// (giá 100, không đơn vị) và luôn có nhãn "Ví dụ minh họa". Màu chỉ dùng token của index.css.

/** Chữ thân của trang hướng dẫn: to hơn phần còn lại của web cho dễ đọc. */
export const BODY_TEXT = "text-base leading-relaxed sm:text-[17px] sm:leading-8";

/**
 * Một mục dạng câu hỏi: câu trả lời 1 câu in đậm → giải thích → (ví dụ/minh họa ở cột phải trên màn
 * rộng) → lưu ý. Dưới lg thanh trên dính cao 56 px nên chừa scroll-mt để tiêu đề không bị che.
 */
export function QuestionSection({
  id,
  title,
  answer,
  children,
  aside,
  note,
  wide = false,
}: {
  id: GuideAnchor;
  title: string;
  answer: ReactNode;
  children?: ReactNode;
  /** Ví dụ hoặc minh họa, đặt cạnh phần chữ khi màn đủ rộng. */
  aside?: ReactNode;
  note?: ReactNode;
  /** Phần minh họa cần cả bề ngang (bảng độ tin cậy): đặt dưới phần chữ thay vì bên cạnh. */
  wide?: boolean;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="@container scroll-mt-20 border-t border-line pt-10 lg:scroll-mt-8">
      <h2 id={`${id}-title`} className="text-2xl font-semibold tracking-tight text-balance sm:text-[1.75rem]">
        {title}
      </h2>
      <div
        className={
          aside && !wide
            ? "mt-5 grid gap-6 @4xl:grid-cols-[minmax(0,36rem)_minmax(0,1fr)] @4xl:gap-10"
            : "mt-5 grid gap-6"
        }
      >
        <div className={`max-w-[38rem] space-y-4 ${BODY_TEXT}`}>
          <p className="border-l-4 border-forecast pl-4 text-lg font-semibold leading-snug text-price sm:text-xl">
            {answer}
          </p>
          {children}
        </div>
        {aside ? <div className="min-w-0 max-w-[38rem] space-y-4 @4xl:pt-1">{aside}</div> : null}
      </div>
      {note ? <Note>{note}</Note> : null}
    </section>
  );
}

/** Ví dụ có số: nền nhạt, nhãn "Ví dụ minh họa" để không ai nhầm với giá thật. */
export function Example({ children, label = "Ví dụ minh họa, không phải giá thật" }: { children: ReactNode; label?: string }) {
  return (
    <figure className="rounded-xl bg-surface-muted p-5">
      <figcaption className="text-sm font-medium text-muted">{label}</figcaption>
      <div className="tabular mt-3 space-y-3 text-base leading-relaxed">{children}</div>
    </figure>
  );
}

export function Note({ children }: { children: ReactNode }) {
  return (
    <div className={`mt-6 max-w-[38rem] rounded-lg bg-warn-bg px-4 py-3 text-warn-fg ${BODY_TEXT}`}>
      <span className="font-semibold">Lưu ý: </span>
      {children}
    </div>
  );
}

// ---------- Minh họa nhỏ ----------

/** Thanh khoảng 80% với mép dưới, mức giữa, mép trên. Vị trí tính theo % của khung low..high có lề. */
export function RangeBar({
  low,
  mid,
  high,
  now,
  compact = false,
}: {
  low: string;
  mid: string;
  high: string;
  /** Giá phiên gần nhất, vẽ vạch mảnh để so. */
  now?: string;
  compact?: boolean;
}) {
  return (
    <div aria-hidden="true" className={compact ? "pt-1" : "pt-6"}>
      <div className="relative h-10">
        <div className="absolute inset-y-2 left-[12%] right-[12%] rounded-md bg-band" />
        <div className="absolute inset-y-0 left-[12%] w-0.5 bg-forecast" />
        <div className="absolute inset-y-0 right-[12%] w-0.5 bg-forecast" />
        <div className="absolute top-1/2 left-[52%] size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-median-dot ring-2 ring-surface" />
        {now ? <div className="absolute -inset-y-1 left-[46%] border-l-2 border-dashed border-muted" /> : null}
        {now && !compact ? (
          <span className="absolute -top-6 left-[46%] -translate-x-1/2 whitespace-nowrap text-xs text-muted">
            hôm nay {now}
          </span>
        ) : null}
      </div>
      <div className="tabular mt-2 grid grid-cols-3 text-sm">
        <span className="text-left">
          <span className="block text-muted">Mép dưới</span>
          <span className="font-semibold">{low}</span>
        </span>
        <span className="text-center">
          <span className="block text-muted">Mức giữa</span>
          <span className="font-semibold">{mid}</span>
        </span>
        <span className="text-right">
          <span className="block text-muted">Mép trên</span>
          <span className="font-semibold">{high}</span>
        </span>
      </div>
    </div>
  );
}

/** Thanh xác suất 0–100% có vạch 50%, giống ProbabilityBadge trên trang sản phẩm. */
export function ProbabilityMeter({ percent, tone }: { percent: number; tone: "up" | "down" | "flat" }) {
  const fill = tone === "up" ? "bg-up" : tone === "down" ? "bg-down" : "bg-muted";
  return (
    <div aria-hidden="true" className="relative h-2 rounded-full bg-line">
      <div className={`h-2 rounded-full ${fill}`} style={{ width: `${percent}%` }} />
      <div className="absolute inset-y-[-3px] left-1/2 w-px bg-price" />
    </div>
  );
}

const LEAN_STYLE = {
  up: { arrow: "▲", color: "text-up", label: "Nghiêng tăng" },
  down: { arrow: "▼", color: "text-down", label: "Nghiêng giảm" },
  flat: { arrow: "◆", color: "text-muted", label: "Chưa rõ xu hướng" },
} as const;

/** Một dòng nhãn hướng như trên web: mũi tên + chữ + số phiên + xác suất (không chỉ dựa vào màu). */
export function LeanSample({ percent, tone, range }: { percent: number; tone: "up" | "down" | "flat"; range: string }) {
  const style = LEAN_STYLE[tone];
  return (
    <div className="space-y-2">
      <p className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className={`font-semibold ${style.color}`}>
          <span aria-hidden="true">{style.arrow} </span>
          {style.label} <span className="font-normal text-muted">· 7 phiên</span>
        </span>
        <span className="tabular text-sm text-muted">
          Xác suất tăng <span className="font-semibold text-price">{percent}%</span>
        </span>
      </p>
      <ProbabilityMeter percent={percent} tone={tone} />
      <p className="text-xs text-muted">{range}</p>
    </div>
  );
}

/** Chấm tròn đếm số lần: đậm = giá thật nằm trong khoảng, rỗng = nằm ngoài. */
export function HitDots({ hits, total, label }: { hits: number; total: number; label: string }) {
  return (
    <div role="img" aria-label={label} className="flex flex-wrap gap-1.5">
      {Array.from({ length: total }, (_, index) => (
        <span
          key={index}
          className={`size-3.5 rounded-full ${index < hits ? "bg-forecast" : "border-2 border-line bg-surface"}`}
        />
      ))}
    </div>
  );
}

/** Ký hiệu trên biểu đồ giá, cùng kiểu chú thích ở trang sản phẩm. */
export function ChartLegendKey() {
  return (
    <ul aria-label="Ký hiệu trên biểu đồ" className="grid gap-3 text-base">
      <li className="flex items-center gap-3">
        <span aria-hidden="true" className="inline-block h-0.5 w-8 shrink-0 bg-price" />
        <span>
          <strong className="font-semibold">Đường liền</strong>: giá cuối phiên đã xảy ra
        </span>
      </li>
      <li className="flex items-center gap-3">
        <span aria-hidden="true" className="inline-block h-4 w-8 shrink-0 border-l-2 border-dashed border-muted" />
        <span>
          <strong className="font-semibold">Vạch dọc</strong>: phiên gần nhất có giá
        </span>
      </li>
      <li className="flex items-center gap-3">
        <span aria-hidden="true" className="inline-block h-4 w-8 shrink-0 rounded-sm bg-band" />
        <span>
          <strong className="font-semibold">Dải xanh</strong>: khoảng 80% của từng phiên tới
        </span>
      </li>
      <li className="flex items-center gap-3">
        <span aria-hidden="true" className="relative inline-block w-8 shrink-0 border-t-2 border-dashed border-forecast">
          <span className="absolute -top-[6px] left-1/2 size-2.5 -translate-x-1/2 rounded-full bg-median-dot" />
        </span>
        <span>
          <strong className="font-semibold">Chấm đỏ</strong>: mức giữa của từng phiên tới
        </span>
      </li>
    </ul>
  );
}

/** Biểu đồ thu nhỏ: đường giá, vạch phiên gần nhất, dải loe và chấm mức giữa. Hình giả, không trục số. */
export function MiniFanChart({ className = "" }: { className?: string }) {
  // Đường giá giả 12 điểm, sau đó 7 phiên dự báo loe dần
  const past = [62, 58, 60, 54, 56, 50, 52, 47, 49, 51, 46, 48];
  const step = 16;
  const lastX = (past.length - 1) * step;
  const lastY = past[past.length - 1];
  const linePath = past.map((y, i) => `${i === 0 ? "M" : "L"}${i * step},${y}`).join(" ");
  const ahead = Array.from({ length: 7 }, (_, i) => i + 1);
  const upper = ahead.map((h) => `L${lastX + h * step},${lastY - 4 - h * 3.2}`).join(" ");
  const lower = [...ahead].reverse().map((h) => `L${lastX + h * step},${lastY + 4 + h * 3.2}`).join(" ");
  const bandPath = `M${lastX},${lastY} ${upper} ${lower} Z`;
  return (
    <svg viewBox={`-4 10 ${lastX + 7 * step + 12} 92`} className={`w-full ${className}`} aria-hidden="true">
      <path d={bandPath} className="fill-band" />
      <line x1={lastX} x2={lastX} y1={14} y2={98} className="stroke-muted" strokeWidth={1} strokeDasharray="3 3" />
      <path d={linePath} className="stroke-price" fill="none" strokeWidth={2} strokeLinejoin="round" />
      <path
        d={`M${lastX},${lastY} ${ahead.map((h) => `L${lastX + h * step},${lastY - h * 0.4}`).join(" ")}`}
        className="stroke-forecast"
        fill="none"
        strokeWidth={1.5}
        strokeDasharray="4 3"
      />
      {ahead.map((h) => (
        <circle key={h} cx={lastX + h * step} cy={lastY - h * 0.4} r={2.6} className="fill-median-dot" />
      ))}
    </svg>
  );
}

/** Dải 7 ô phiên, ô được chọn tô đậm: minh họa "Sau h phiên". */
export function HorizonStrip({ selected = 7 }: { selected?: number }) {
  return (
    <ol aria-hidden="true" className="grid grid-cols-7 gap-1.5">
      {Array.from({ length: 7 }, (_, i) => i + 1).map((h) => (
        <li
          key={h}
          className={`tabular rounded-md py-2 text-center text-sm ${
            h === selected ? "bg-price font-semibold text-on-price" : "bg-surface text-muted ring-1 ring-line"
          }`}
        >
          {h}
        </li>
      ))}
    </ol>
  );
}
