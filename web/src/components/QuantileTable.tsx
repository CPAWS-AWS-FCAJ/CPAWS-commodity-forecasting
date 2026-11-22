import type { AssetId, Currency, ForecastDetail } from "../api/types";
import { formatDate, formatPrice, formatReturnPercent } from "../lib/format";
import { horizonView } from "../lib/forecast";
import { convertPrice, displayUnit } from "../lib/units";
import { GUIDE_ANCHORS, HowToRead } from "./HowToRead";

interface Props {
  asset: AssetId;
  detail: ForecastDetail;
  currency: Currency;
  /** false → bỏ cột giá (vàng/bạc khi VITE_SHOW_METAL_PRICES=false). */
  showPrices?: boolean;
}

/** Tiêu đề khối (dùng lại trong test). */
export const QUANTILE_TABLE_TITLE = "Bảng chi tiết theo từng phiên";

function QuantileHead({ level, hint }: { level: string; hint: string }) {
  return (
    <th scope="col" className="px-4 py-2 text-right font-medium">
      {level}
      <span className="block font-normal">{hint}</span>
    </th>
  );
}

/** Bảng chế độ nâng cao: h = 1…7, q10 / q50 / q90 (log return %), khoảng giá và xác suất tăng. */
export function QuantileTable({ asset, detail, currency, showPrices = true }: Props) {
  const rate = detail.fx.usd_vnd;
  const unit = displayUnit(asset, currency);
  const price = (usd: number) => formatPrice(asset, convertPrice(asset, usd, currency, rate), currency);
  return (
    <section aria-labelledby="quantile-table-title" className="rounded-lg border border-line bg-surface">
      <div className="px-4 pt-4 sm:px-5">
        <h2 id="quantile-table-title" className="text-lg font-semibold">
          {QUANTILE_TABLE_TITLE}
          <span className="block text-sm font-normal text-muted">
            {showPrices ? `Phân vị của log return và khoảng giá (${unit})` : "Phân vị của log return"}
          </span>
        </h2>
        <HowToRead anchor={GUIDE_ANCHORS.quantiles} topic="phân vị q10, q50, q90">
          mỗi hàng là một phiên tới. q50 là mức giữa; q10 và q90 là mép dưới và mép trên của khoảng 80% mà dự báo
          đặt ra{showPrices ? ", cột giá là hai mép đó quy đổi từ giá cuối phiên gần nhất" : ""}. Đây là phân vị
          của dự báo, chưa phải xác suất đã kiểm chứng.
        </HowToRead>
      </div>
      <div className="mt-3 overflow-x-auto">
        <table aria-labelledby="quantile-table-title" className="tabular w-full min-w-[560px] text-sm">
          <thead className="bg-surface-muted text-left text-xs text-muted">
            <tr>
              <th scope="col" className="px-4 py-2 font-medium">
                Sau
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Phiên
              </th>
              <QuantileHead level="q10" hint="mép dưới" />
              <QuantileHead level="q50" hint="mức giữa" />
              <QuantileHead level="q90" hint="mép trên" />
              {showPrices ? (
                <th scope="col" className="px-4 py-2 text-right font-medium">
                  Giá q10–q90
                  <span className="block font-normal">{unit}</span>
                </th>
              ) : null}
              <th scope="col" className="px-4 py-2 text-right font-medium">
                Xác suất tăng
              </th>
            </tr>
          </thead>
          <tbody>
            {detail.horizons.map((horizon) => {
              const view = horizonView(detail, horizon);
              return (
                <tr key={horizon.h} className="border-t border-line">
                  <th scope="row" className="px-4 py-2 text-left font-medium">
                    {horizon.h} phiên
                  </th>
                  <td className="px-4 py-2">{formatDate(horizon.target_date)}</td>
                  <td className="px-4 py-2 text-right">{formatReturnPercent(view.returnLow, 2)}</td>
                  <td className="px-4 py-2 text-right">{formatReturnPercent(view.returnMid, 2)}</td>
                  <td className="px-4 py-2 text-right">{formatReturnPercent(view.returnHigh, 2)}</td>
                  {showPrices ? (
                    <td className="px-4 py-2 text-right">
                      {price(view.low)}–{price(view.high)}
                    </td>
                  ) : null}
                  <td className="px-4 py-2 text-right">{view.probability.probUpLabel}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
