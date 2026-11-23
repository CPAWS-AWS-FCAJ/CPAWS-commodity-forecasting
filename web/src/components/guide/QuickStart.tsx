import type { ReactNode } from "react";
import { GUIDE_ANCHORS } from "../HowToRead";
import type { GuideAnchor } from "../HowToRead";
import { HitDots, HorizonStrip, ProbabilityMeter, RangeBar } from "./GuideBlocks";

// "Đọc dự báo trong 30 giây": 4 bước, mỗi bước một minh họa nhỏ tĩnh (không có giá thật).

interface Step {
  title: string;
  text: string;
  more: GuideAnchor;
  picture: ReactNode;
}

const STEPS: Step[] = [
  {
    title: "Chọn số phiên muốn xem",
    text: "Mặc định là 7 phiên giao dịch tới, tức khoảng một tuần rưỡi. Bạn có thể chọn gần hơn.",
    more: GUIDE_ANCHORS.horizon,
    picture: <HorizonStrip selected={7} />,
  },
  {
    title: "Nhìn khoảng giá 80%",
    text: "Dự báo không đưa một con số mà đưa một khoảng: giá có thể nằm từ mép dưới tới mép trên.",
    more: GUIDE_ANCHORS.interval,
    picture: <RangeBar low="97" mid="100,3" high="104" compact />,
  },
  {
    title: "Xem xác suất tăng",
    text: "Trên 50% là dự báo nghiêng về tăng, dưới 50% nghiêng về giảm, quanh 50% là chưa rõ.",
    more: GUIDE_ANCHORS.probUp,
    picture: (
      <div className="space-y-2 pt-2">
        <ProbabilityMeter percent={53} tone="flat" />
        <p className="tabular text-sm text-muted">
          <span aria-hidden="true">◆ </span>Chưa rõ xu hướng · 53%
        </p>
      </div>
    ),
  },
  {
    title: "Xem dự báo gần đây trúng tới đâu",
    text: "Khối Độ tin cậy đếm xem giá thật có thường rơi vào khoảng 80% không. Mục tiêu là khoảng 8 trên 10 lần.",
    more: GUIDE_ANCHORS.reliability,
    picture: <HitDots hits={8} total={10} label="Minh họa 8 trên 10 lần giá thật nằm trong khoảng" />,
  },
];

export function QuickStart() {
  return (
    <section
      id={GUIDE_ANCHORS.quickStart}
      aria-labelledby={`${GUIDE_ANCHORS.quickStart}-title`}
      className="scroll-mt-20 lg:scroll-mt-8"
    >
      <h2 id={`${GUIDE_ANCHORS.quickStart}-title`} className="text-2xl font-semibold tracking-tight sm:text-[1.75rem]">
        Đọc dự báo trong 30 giây
      </h2>
      <p className="mt-2 text-base text-muted">Bốn bước, theo thứ tự từ trên xuống của trang sản phẩm. Số trong hình chỉ để minh họa.</p>
      <ol className="mt-6 grid gap-4 sm:grid-cols-2 2xl:grid-cols-4">
        {STEPS.map((step, index) => (
          <li key={step.title} className="flex flex-col rounded-xl border border-line bg-surface p-5">
            <p className="flex items-center gap-3">
              <span
                aria-hidden="true"
                className="tabular grid size-8 shrink-0 place-items-center rounded-full bg-price text-sm font-semibold text-on-price"
              >
                {index + 1}
              </span>
              <span className="text-lg font-semibold leading-snug">
                <span className="sr-only">Bước {index + 1}: </span>
                {step.title}
              </span>
            </p>
            <div className="mt-4 sm:min-h-20">{step.picture}</div>
            <p className="mt-4 flex-1 text-base leading-relaxed">{step.text}</p>
            <a
              href={`#${step.more}`}
              className="mt-3 self-start text-sm text-forecast underline underline-offset-2 pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center"
            >
              Đọc kỹ hơn<span className="sr-only"> về {step.title.toLowerCase()}</span>
            </a>
          </li>
        ))}
      </ol>
    </section>
  );
}
