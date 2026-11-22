import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import type { AssetId, Currency, ForecastDetail } from "../api/types";
import { formatDate, formatPrice, formatReturnPercent } from "../lib/format";
import { matchesMedia, REDUCED_MOTION } from "../lib/media";
import { horizonView } from "../lib/forecast";
import type { HorizonView, Lean } from "../lib/forecast";
import { convertPrice, displayUnit } from "../lib/units";
import { GUIDE_ANCHORS, HowToRead } from "./HowToRead";
import { Swap } from "./Swap";

// Nền nhạt theo spec dashboard: nghiêng tăng xanh lá, nghiêng giảm đỏ, chưa rõ xám (token đổi theo giao
// diện sáng/tối). Nhãn luôn có chữ và mũi tên nên không chỉ dựa vào màu.
const ARROW: Record<Lean, string> = { up: "▲", down: "▼", flat: "◆" };
const PILL: Record<Lean, string> = {
  up: "bg-up-bg text-up",
  down: "bg-down-bg text-down",
  flat: "bg-surface-muted text-muted",
};

interface Props {
  asset: AssetId;
  detail: ForecastDetail;
  currency: Currency;
  /** Vàng/bạc khi VITE_SHOW_METAL_PRICES=false: chỉ hiện % thay đổi, không hiện giá. */
  hidePrice: boolean;
  /** Số phiên đang chọn ở phần tóm tắt; bấm một thẻ để đổi. */
  selected: number;
  onSelect: (h: number) => void;
}

/**
 * Dải 7 thẻ h = 1…7 (spec dashboard của Khải, skill forecast-display): mỗi thẻ có phiên đích,
 * nhãn hướng 60/40 kèm "· h phiên", xác suất tăng từ `prob_up` của API, khoảng 80% q10–q90
 * (dầu: giá + %; vàng/bạc khi ẩn giá: chỉ %) và mức giữa q50. Web không tự tính lại giá.
 * Dưới sm (điện thoại) 7 thẻ nằm trên một dải cuộn ngang có snap, thẻ sau ló ra mép phải; đủ thông tin
 * như máy tính mà không chiếm ~3 màn hình. Đổi số phiên ở chỗ khác thì dải tự cuộn tới thẻ đang chọn.
 */
export function HorizonCards({ asset, detail, currency, hidePrice, selected, onSelect }: Props) {
  const views = [...detail.horizons].sort((a, b) => a.h - b.h).map((horizon) => horizonView(detail, horizon));
  const stripRef = useRef<HTMLUListElement>(null);
  const shownSelected = useRef(selected);

  // Chỉ khi người dùng đổi số phiên (không cuộn lúc mới mở trang), chỉ cuộn ngang trong dải (không kéo
  // cả trang theo chiều dọc), và chỉ khi dải đang cuộn được.
  useEffect(() => {
    if (shownSelected.current === selected) return;
    shownSelected.current = selected;
    const strip = stripRef.current;
    if (!strip || strip.scrollWidth <= strip.clientWidth) return;
    const card = strip.querySelector<HTMLElement>(`[data-h="${selected}"]`);
    if (!card) return;
    const left = card.offsetLeft - strip.offsetLeft - 16;
    const right = left + card.offsetWidth + 32;
    if (left >= strip.scrollLeft && right <= strip.scrollLeft + strip.clientWidth) return;
    strip.scrollTo?.({ left: Math.max(0, left), behavior: matchesMedia(REDUCED_MOTION) ? "auto" : "smooth" });
  }, [selected]);

  return (
    <section aria-labelledby="horizon-cards-title">
      <h2 id="horizon-cards-title" className="text-lg font-semibold">
        Dự báo cho từng phiên trong 7 phiên tới <span className="text-sm font-normal text-muted">(h = 1…7)</span>
      </h2>
      <HowToRead anchor={GUIDE_ANCHORS.horizon} topic="dự báo theo số phiên">
        mỗi thẻ là một phiên giao dịch tới, bấm để xem chi tiết phía trên. “Khoảng 80%” là khoảng q10–q90 mà dự báo
        đặt ra, chưa phải mức đã kiểm chứng. Nhãn “Nghiêng tăng” khi xác suất tăng từ 60%, “Nghiêng giảm” khi từ 40%
        trở xuống, còn lại là “Chưa rõ xu hướng”.
      </HowToRead>
      <ul
        ref={stripRef}
        aria-label="7 phiên tới"
        className="-mx-4 mt-3 grid auto-cols-[78%] grid-flow-col gap-3 overflow-x-auto scroll-px-4 px-4 pb-2 snap-x snap-mandatory sm:mx-0 sm:auto-cols-auto sm:grid-flow-row sm:grid-cols-[repeat(auto-fill,minmax(13rem,1fr))] sm:overflow-visible sm:px-0 sm:pb-0 sm:snap-none"
      >
        {views.map((view, index) => (
          // Thẻ xuất hiện so le 40ms/thẻ (tối đa 6 bước) khi mở trang
          <li key={view.h} data-h={view.h} className="stagger-item snap-start" style={{ "--i": index } as CSSProperties}>
            <HorizonCard
              asset={asset}
              view={view}
              currency={currency}
              usdVnd={detail.fx.usd_vnd}
              hidePrice={hidePrice}
              active={view.h === selected}
              onSelect={onSelect}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}

function HorizonCard({
  asset,
  view,
  currency,
  usdVnd,
  hidePrice,
  active,
  onSelect,
}: {
  asset: AssetId;
  view: HorizonView;
  currency: Currency;
  usdVnd: number;
  hidePrice: boolean;
  active: boolean;
  onSelect: (h: number) => void;
}) {
  const { probability } = view;
  const price = (usd: number) => formatPrice(asset, convertPrice(asset, usd, currency, usdVnd), currency);
  const unit = displayUnit(asset, currency);
  const returnRange = `${formatReturnPercent(view.returnLow)} đến ${formatReturnPercent(view.returnHigh)}`;

  return (
    <button
      type="button"
      aria-pressed={active}
      aria-label={`Sau ${view.h} phiên: ${probability.label}, xác suất tăng ${probability.probUpLabel}`}
      onClick={() => onSelect(view.h)}
      className={`lift tabular flex h-full w-full flex-col rounded-lg border bg-surface p-4 text-left text-sm hover:border-forecast ${
        active ? "border-forecast ring-1 ring-forecast" : "border-line"
      }`}
    >
      <span className="flex items-baseline justify-between gap-2">
        <span className="font-semibold">Sau {view.h} phiên</span>
        <span className="text-xs text-muted">phiên {formatDate(view.targetDate)}</span>
      </span>

      <span className={`mt-2 inline-flex w-fit rounded-full px-2 py-0.5 text-xs font-semibold ${PILL[probability.lean]}`}>
        <span aria-hidden="true">{ARROW[probability.lean]}&nbsp;</span>
        {probability.label} · {view.h} phiên
      </span>
      <span className="mt-1">
        Xác suất tăng <strong>{probability.probUpLabel}</strong>
      </span>

      <span className="mt-3 text-xs text-muted">Khoảng 80%</span>
      {/* Đổi USD/VND: giá trong thẻ hiện lại bằng một nhịp mờ ngắn */}
      <Swap value={currency} className="flex flex-col">
        {hidePrice ? (
          <span className="font-semibold">{returnRange}</span>
        ) : (
          <>
            <span className="font-semibold">
              {price(view.low)}–{price(view.high)} <span className="text-xs font-normal text-muted">{unit}</span>
            </span>
            <span className="text-xs text-muted">{returnRange}</span>
          </>
        )}

        <span className="mt-2 text-xs text-muted">
          Mức giữa:{" "}
          {hidePrice
            ? formatReturnPercent(view.returnMid)
            : `${price(view.mid)} ${unit} (${formatReturnPercent(view.returnMid)})`}
        </span>
      </Swap>
    </button>
  );
}
