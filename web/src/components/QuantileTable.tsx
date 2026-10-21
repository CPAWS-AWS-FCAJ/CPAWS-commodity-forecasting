import type { AssetId, Currency, ForecastDetail } from "../api/types";
import { formatDate, formatPrice, formatReturnPercent } from "../lib/format";
import { horizonView } from "../lib/forecast";
import { convertPrice, displayUnit } from "../lib/units";

interface Props {
  asset: AssetId;
  detail: ForecastDetail;
  currency: Currency;
}

/** Bảng chế độ nâng cao: h = 1…7, q10 / q50 / q90 (log return %), khoảng giá và xác suất tăng. */
export function QuantileTable({ asset, detail, currency }: Props) {
  const rate = detail.fx.usd_vnd;
  const price = (usd: number) => formatPrice(asset, convertPrice(asset, usd, currency, rate), currency);
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-white">
      <table className="tabular w-full min-w-[640px] text-sm">
        <caption className="px-4 py-3 text-left text-sm font-medium">
          Phân vị của log return và khoảng giá ({displayUnit(asset, currency)})
        </caption>
        <thead className="bg-canvas text-left text-xs text-muted">
          <tr>
            <th scope="col" className="px-4 py-2 font-medium">h</th>
            <th scope="col" className="px-4 py-2 font-medium">Ngày</th>
            <th scope="col" className="px-4 py-2 text-right font-medium">q10</th>
            <th scope="col" className="px-4 py-2 text-right font-medium">q50</th>
            <th scope="col" className="px-4 py-2 text-right font-medium">q90</th>
            <th scope="col" className="px-4 py-2 text-right font-medium">Giá q10–q90</th>
            <th scope="col" className="px-4 py-2 text-right font-medium">Xác suất tăng</th>
          </tr>
        </thead>
        <tbody>
          {detail.horizons.map((horizon) => {
            const view = horizonView(detail, horizon);
            return (
              <tr key={horizon.h} className="border-t border-line">
                <th scope="row" className="px-4 py-2 text-left font-medium">{horizon.h}</th>
                <td className="px-4 py-2">{formatDate(horizon.target_date)}</td>
                <td className="px-4 py-2 text-right">{formatReturnPercent(view.returnLow)}</td>
                <td className="px-4 py-2 text-right">{formatReturnPercent(view.returnMid)}</td>
                <td className="px-4 py-2 text-right">{formatReturnPercent(view.returnHigh)}</td>
                <td className="px-4 py-2 text-right">
                  {price(view.low)}–{price(view.high)}
                </td>
                <td className="px-4 py-2 text-right">{view.probability.probUpLabel}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
