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

/** Một phân vị trong thẻ phiên (dạng danh sách trên điện thoại). */
function QuantileCell({ level, hint, value }: { level: string; hint: string; value: string }) {
  return (
    <div className="rounded-md bg-surface-muted px-2 py-1.5">
      <dt className="text-xs text-muted">
        {level}
        <span className="block">{hint}</span>
      </dt>
      <dd className="mt-0.5 font-medium">{value}</dd>
    </div>
  );
}

/**
 * Bảng chế độ nâng cao: h = 1…7, q10 / q50 / q90 (log return %), khoảng giá và xác suất tăng.
 * Dưới sm (điện thoại) bảng 7 cột không vừa màn: hiện cùng số liệu dạng danh sách, mỗi phiên một thẻ,
 * không phải cuộn ngang. Từ sm hiện bảng như cũ.
 */
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
      <ol aria-label={QUANTILE_TABLE_TITLE} className="mt-3 divide-y divide-line border-t border-line sm:hidden">
        {detail.horizons.map((horizon) => {
          const view = horizonView(detail, horizon);
          return (
            <li key={horizon.h} className="tabular px-4 py-3 text-sm">
              <p className="flex items-baseline justify-between gap-2">
                <span className="font-medium">Sau {horizon.h} phiên</span>
                <span className="text-xs text-muted">phiên {formatDate(horizon.target_date)}</span>
              </p>
              <dl className="mt-2 grid grid-cols-3 gap-2">
                <QuantileCell level="q10" hint="mép dưới" value={formatReturnPercent(view.returnLow, 2)} />
                <QuantileCell level="q50" hint="mức giữa" value={formatReturnPercent(view.returnMid, 2)} />
                <QuantileCell level="q90" hint="mép trên" value={formatReturnPercent(view.returnHigh, 2)} />
              </dl>
              <dl className="mt-2 space-y-1">
                {showPrices ? (
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <dt className="text-xs text-muted">Giá q10–q90 ({unit})</dt>
                    <dd>
                      {price(view.low)}–{price(view.high)}
                    </dd>
                  </div>
                ) : null}
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <dt className="text-xs text-muted">Xác suất tăng</dt>
                  <dd>{view.probability.probUpLabel}</dd>
                </div>
              </dl>
            </li>
          );
        })}
      </ol>
      <div className="mt-3 hidden overflow-x-auto sm:block">
        <table aria-labelledby="quantile-table-title" className="tabular w-full min-w-[560px] text-sm">
          <thead className="bg-surface-muted text-left text-xs text-muted">
            <tr>
              <th scope="col" className="whitespace-nowrap px-4 py-2 font-medium">
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
                  <th scope="row" className="whitespace-nowrap px-4 py-2 text-left font-medium">
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
