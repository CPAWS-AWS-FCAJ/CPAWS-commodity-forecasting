import { ACCURACY_METRIC_TEXT } from "../../lib/accuracy";
import { BODY_TEXT, Example, HitDots } from "./GuideBlocks";

// Phần giải thích "Độ tin cậy 8 tuần" và bảng "Trong khoảng 80%" X/Y theo h (trang Độ chính xác,
// chế độ Nâng cao). Số trong bảng là số giả để minh họa, không lấy từ API hay fixture.

const SAMPLE_ROWS = [
  { h: 1, hits: 10, total: 16 },
  { h: 2, hits: 12, total: 15 },
  { h: 3, hits: 11, total: 14 },
  { h: 4, hits: 11, total: 13 },
  { h: 5, hits: 10, total: 12 },
  { h: 6, hits: 9, total: 11 },
  { h: 7, hits: 8, total: 10 },
];

const METRICS = [ACCURACY_METRIC_TEXT.coverage, ACCURACY_METRIC_TEXT.width, ACCURACY_METRIC_TEXT.sign];

/** Ba con số chính của khối Độ tin cậy, dùng đúng chữ của khối trên trang sản phẩm. */
export function ReliabilityMetrics() {
  return (
    <div>
      <h3 className="text-lg font-semibold">Ba con số chính</h3>
      <p className={`mt-1 max-w-[38rem] text-muted ${BODY_TEXT}`}>
        Chỉ hiện khi đã chấm đủ số ngày. Cả ba gộp chung 7 mức số phiên.
      </p>
      <dl className="mt-4 grid gap-4 md:grid-cols-3">
        {METRICS.map((metric) => (
          <div key={metric.name} className="rounded-xl border border-line bg-surface p-5">
            <dt className="text-base font-semibold leading-snug">{metric.name}</dt>
            <dd className="mt-2 text-base leading-relaxed">{metric.meaning}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Bảng mẫu X/Y theo h, mỗi hàng kèm dãy chấm để thấy X trên Y bằng mắt. */
export function HorizonCountExplainer() {
  return (
    <div className="grid gap-6 @4xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] @4xl:gap-10">
      <div className={`max-w-[38rem] space-y-4 ${BODY_TEXT}`}>
        <h3 className="text-lg font-semibold">Bảng “Trong khoảng 80%” theo h</h3>
        <p>
          Ở trang Độ chính xác, chế độ Nâng cao, mỗi sản phẩm có bảng 7 hàng, mỗi hàng một số phiên h. Ô bên phải
          ghi dạng <strong>X/Y</strong>.
        </p>
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <strong>Y</strong>: số lần đã có giá thật sau h phiên để so với dự báo.
          </li>
          <li>
            <strong>X</strong>: trong Y lần đó, số lần giá thật nằm trong khoảng 80%.
          </li>
          <li>
            Mục tiêu là X bằng <strong>khoảng 8 phần 10</strong> của Y. Với 16 lần, mục tiêu là khoảng 13 lần.
          </li>
          <li>
            <strong>Y nhỏ dần khi h lớn dần</strong>: dự báo cho 7 phiên tới phải chờ đủ 7 phiên mới có giá thật để
            chấm, nên những dự báo mới nhất chưa kịp vào hàng h = 7.
          </li>
          <li>Ô “—” nghĩa là chưa có lần nào chấm được ở số phiên đó.</li>
        </ul>
      </div>

      <Example>
        <table className="w-full text-sm">
          <caption className="sr-only">Bảng mẫu: số lần giá thật nằm trong khoảng 80% trên số lần đã chấm, theo h</caption>
          <thead>
            <tr className="text-left text-muted">
              <th scope="col" className="w-8 pb-2 pr-3 font-medium">h</th>
              <th scope="col" className="w-32 whitespace-nowrap pb-2 pr-3 font-medium">Trong khoảng 80%</th>
              <th scope="col" className="pb-2 font-medium">
                <span className="sr-only">Hình đếm</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {SAMPLE_ROWS.map((row) => (
              <tr key={row.h} className="border-t border-line align-middle">
                <th scope="row" className="py-2 pr-3 text-left font-medium">
                  {row.h}
                </th>
                <td className="py-2 pr-3 font-semibold">
                  {row.hits}/{row.total}
                </td>
                <td className="py-2">
                  <HitDots
                    hits={row.hits}
                    total={row.total}
                    label={`${row.hits} chấm đậm trên ${row.total} chấm`}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="size-3 rounded-full bg-forecast" /> giá thật trong khoảng
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="size-3 rounded-full border-2 border-line bg-surface" /> ngoài khoảng
          </span>
        </p>
      </Example>
    </div>
  );
}

/** Đọc một ô cụ thể: 10/16 ở h = 1. */
export function ReadOneCell() {
  return (
    <Example label="Ví dụ minh họa: đọc ô 10/16 ở hàng h = 1">
      <ol className="list-decimal space-y-2 pl-5">
        <li>Có 16 ngày dự báo mà giá thật của 1 phiên sau đó đã có.</li>
        <li>Trong 16 lần đó, 10 lần giá thật nằm trong khoảng 80%; 6 lần nằm ngoài.</li>
        <li>
          10/16 là khoảng 6 phần 10, thấp hơn mục tiêu 8 phần 10 (khoảng 13/16). Có thể khoảng đang hơi hẹp ở 1 phiên,
          nhưng 16 lần còn quá ít để kết luận.
        </li>
      </ol>
    </Example>
  );
}

/** "Đang thu thập (16/20)": thanh tiến độ minh họa. */
export function CollectingExplainer() {
  return (
    <div className="grid gap-6 @4xl:grid-cols-[minmax(0,36rem)_minmax(0,1fr)] @4xl:gap-10">
      <div className={`max-w-[38rem] space-y-4 ${BODY_TEXT}`}>
        <h3 className="text-lg font-semibold">“Đang thu thập (16/20)” nghĩa là gì?</h3>
        <p>
          Hệ thống đã chấm được 16 ngày dự báo, cần ít nhất 20 ngày mới hiện ba con số chính. Lúc này{" "}
          <strong>chưa đủ ngày nên chưa kết luận</strong>; quay lại sau vài phiên nữa.
        </p>
        <p>
          “Chưa có kết quả đánh giá” nghĩa là chưa có ngày nào chấm được. Dòng “Kể từ” cho biết ngày dự báo đầu tiên
          được tính.
        </p>
      </div>
      <Example>
        <p className="text-muted">Đang thu thập (16/20)</p>
        <div aria-hidden="true" className="h-2.5 rounded-full bg-line">
          <div className="h-2.5 w-4/5 rounded-full bg-forecast" />
        </div>
        <p className="text-sm text-muted">16 ngày đã chấm trên 20 ngày tối thiểu</p>
      </Example>
    </div>
  );
}
