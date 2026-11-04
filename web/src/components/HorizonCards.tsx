import type { AssetId, Currency, ForecastDetail } from "../api/types";
import { formatDate, formatPrice, formatReturnPercent } from "../lib/format";
import { horizonView } from "../lib/forecast";
import type { HorizonView, Lean } from "../lib/forecast";
import { convertPrice, displayUnit } from "../lib/units";

// Màu nhạt theo spec dashboard: nghiêng tăng xanh lá, nghiêng giảm đỏ, chưa rõ xám.
// Nhãn luôn có chữ và mũi tên nên không chỉ dựa vào màu.
const ARROW: Record<Lean, string> = { up: "▲", down: "▼", flat: "◆" };
const PILL: Record<Lean, string> = {
  up: "bg-green-50 text-up",
  down: "bg-red-50 text-down",
  flat: "bg-canvas text-muted",
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
 */
export function HorizonCards({ asset, detail, currency, hidePrice, selected, onSelect }: Props) {
  const views = [...detail.horizons].sort((a, b) => a.h - b.h).map((horizon) => horizonView(detail, horizon));
  return (
    <section aria-labelledby="horizon-cards-title">
      <h2 id="horizon-cards-title" className="text-lg font-semibold">
        Dự báo theo số phiên giao dịch (h = 1…7)
      </h2>
      <p className="mt-1 text-xs text-muted">
        Khoảng 80%: kết quả sau h phiên nhiều khả năng nằm trong khoảng này (q10–q90, xác suất danh nghĩa 80%). Nhãn: xác suất
        tăng từ 60% là “Nghiêng tăng”, từ 40% trở xuống là “Nghiêng giảm”, còn lại “Chưa rõ xu hướng”.
      </p>
      <ul className="mt-3 grid grid-cols-[repeat(auto-fill,minmax(13rem,1fr))] gap-3">
        {views.map((view) => (
          <li key={view.h}>
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
      className={`tabular flex h-full w-full flex-col rounded-lg border bg-white p-4 text-left text-sm transition hover:border-forecast ${
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
    </button>
  );
}
