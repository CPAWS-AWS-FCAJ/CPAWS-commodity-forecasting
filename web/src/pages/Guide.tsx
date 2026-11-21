import { useEffect } from "react";
import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { config } from "../api/config";
import { GUIDE_ANCHORS } from "../components/HowToRead";
import type { GuideAnchor } from "../components/HowToRead";
import { ACCURACY_METRIC_TEXT } from "../lib/accuracy";
import { AMOUNT_NOTE } from "../lib/amount";
import { GOLD_VND_NOTE, SOURCE_ATTRIBUTION } from "../lib/source";

// Trang "Cách đọc dự báo": chỉ có chữ và ví dụ số đơn giản (giá 100), KHÔNG có giá thật hay số dự báo,
// không gọi API, nên để công khai được. Lời lẽ theo ADR-0008 và skill forecast-display: không hứa hẹn,
// không gọi q10–q90 là xác suất đã kiểm chứng.

interface Section {
  id: GuideAnchor;
  title: string;
}

const SECTIONS: Section[] = [
  { id: GUIDE_ANCHORS.chart, title: "Đọc biểu đồ giá và dự báo" },
  { id: GUIDE_ANCHORS.logReturn, title: "Log return là gì" },
  { id: GUIDE_ANCHORS.horizon, title: "Dự báo theo số phiên h" },
  { id: GUIDE_ANCHORS.quantiles, title: "Phân vị q05 đến q95" },
  { id: GUIDE_ANCHORS.interval, title: "Khoảng 80% và khoảng giá" },
  { id: GUIDE_ANCHORS.probUp, title: "Xác suất tăng" },
  { id: GUIDE_ANCHORS.baseline, title: "Mốc thống kê 252 phiên" },
  { id: GUIDE_ANCHORS.reliability, title: "Độ tin cậy 8 tuần" },
  { id: GUIDE_ANCHORS.roll, title: "Đáo hạn hợp đồng dầu" },
  { id: GUIDE_ANCHORS.sources, title: "Nguồn dữ liệu" },
  { id: GUIDE_ANCHORS.vnd, title: "Quy đổi VND và số tiền" },
];

function titleOf(id: GuideAnchor): string {
  return SECTIONS.find((section) => section.id === id)?.title ?? id;
}

function GuideSection({ id, children }: { id: GuideAnchor; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-6 border-t border-line pt-6">
      <h2 id={`${id}-title`} className="text-lg font-semibold">
        {titleOf(id)}
      </h2>
      <div className="mt-2 space-y-3 text-base leading-relaxed">{children}</div>
    </section>
  );
}

/** Ví dụ minh họa có số: tách khỏi đoạn văn để dễ dò. */
function Example({ children }: { children: ReactNode }) {
  return (
    <div className="tabular rounded-md border border-line bg-surface px-4 py-3 text-sm">
      <p className="text-xs text-muted">Ví dụ minh họa, không phải giá thật</p>
      <div className="mt-1 space-y-1">{children}</div>
    </div>
  );
}

/** Chú thích ký hiệu trên biểu đồ, cùng kiểu với chú thích ở trang sản phẩm. */
function ChartLegendKey() {
  return (
    <ul aria-label="Ký hiệu trên biểu đồ" className="grid gap-2 text-sm sm:grid-cols-2">
      <li className="flex items-center gap-2">
        <span aria-hidden="true" className="inline-block h-0.5 w-6 shrink-0 bg-price" />
        Đường liền: giá cuối phiên thực tế
      </li>
      <li className="flex items-center gap-2">
        <span aria-hidden="true" className="relative inline-block w-6 shrink-0 border-t-2 border-dashed border-forecast">
          <span className="absolute -top-[5px] left-1/2 size-2 -translate-x-1/2 rounded-full bg-median-dot" />
        </span>
        Nét đứt và chấm đỏ: trung vị dự báo từng phiên
      </li>
      <li className="flex items-center gap-2">
        <span aria-hidden="true" className="inline-block h-3 w-6 shrink-0 rounded-sm bg-band" />
        Dải xanh: khoảng 80% (q10–q90)
      </li>
      <li className="flex items-center gap-2">
        <span aria-hidden="true" className="inline-block h-4 w-6 shrink-0 border-l border-dashed border-muted" />
        Vạch dọc: phiên gần nhất có giá
      </li>
    </ul>
  );
}

export default function Guide() {
  const { hash } = useLocation();

  // Router không tự cuộn tới anchor khi đi từ trang khác vào /guide#...
  useEffect(() => {
    if (!hash) return;
    const target = document.getElementById(decodeURIComponent(hash.slice(1)));
    target?.scrollIntoView?.({ block: "start" });
  }, [hash]);

  return (
    <div className="lg:grid lg:grid-cols-[14rem_minmax(0,1fr)] lg:gap-x-10">
      {/* Thứ tự đọc: tiêu đề → mục lục → nội dung; trên màn rộng mục lục thành cột trái, dính khi cuộn */}
      <header className="max-w-prose lg:col-start-2 lg:row-start-1">
        <h1 className="text-2xl font-bold">Cách đọc dự báo</h1>
        <p className="mt-2 text-base leading-relaxed text-muted">
          CPAWS dự báo vàng, bạc, dầu Brent và dầu WTI cho 1 đến 7 phiên giao dịch tới. Mỗi dự báo là một khoảng,
          không phải một con số chắc chắn. Trang này giải thích từng khái niệm bằng ví dụ đơn giản; số trong ví dụ
          chỉ để minh họa.
        </p>
      </header>

      <nav
        aria-label="Mục lục"
        className="mt-6 lg:sticky lg:top-6 lg:col-start-1 lg:row-span-2 lg:row-start-1 lg:mt-0 lg:self-start"
      >
        <p className="text-sm font-medium">Mục lục</p>
        <ol className="mt-2 space-y-1 text-sm">
          {SECTIONS.map((section) => (
            <li key={section.id}>
              <a href={`#${section.id}`} className="text-muted underline-offset-2 hover:text-price hover:underline">
                {section.title}
              </a>
            </li>
          ))}
        </ol>
      </nav>

      <article className="mt-6 max-w-prose space-y-6 lg:col-start-2 lg:row-start-2">
        <GuideSection id={GUIDE_ANCHORS.chart}>
          <p>
            Biểu đồ “Giá thực tế và dự báo” ghép hai phần: bên trái là giá cuối phiên đã có, bên phải vạch “Phiên gần
            nhất” là 7 phiên dự báo.
          </p>
          <ChartLegendKey />
          <p>
            <strong>Chấm đỏ chỉ đánh dấu mức giữa (trung vị) của từng phiên, không có nghĩa là giảm.</strong> Ở những
            chỗ khác trên trang, tăng và giảm luôn đi kèm mũi tên và chữ: ▲ tăng, ▼ giảm.
          </p>
          <p>
            Chọn mốc 1 tháng, 6 tháng, 1 năm hoặc 2 năm để xem xa hơn; mốc nào chưa đủ dữ liệu thì nút đó bị tắt và có
            ghi lý do. Muốn phóng to một đoạn, kéo hai đầu thanh nhỏ dưới biểu đồ hoặc bấm “Phóng to”; bấm “Đặt lại”
            để về cả mốc, khi đó phần dự báo luôn nằm trong khung. Trục giá không bắt đầu từ 0 để thấy rõ biến động.
          </p>
        </GuideSection>

        <GuideSection id={GUIDE_ANCHORS.logReturn}>
          <p>
            Hệ thống không đoán thẳng mức giá mà đoán <strong>log return</strong>: mức thay đổi của giá sau h phiên,
            tính bằng logarit tự nhiên của tỷ lệ giá sau so với giá hiện tại. Với thay đổi nhỏ, log return gần bằng %
            thay đổi quen thuộc.
          </p>
          <Example>
            <p>Giá hiện tại 100, sau 1 phiên là 102: % thay đổi là +2%, log return là ln(102 / 100) ≈ +1,98%.</p>
            <p>Giá đi từ 100 xuống 99: % thay đổi là −1%, log return ≈ −1,01%.</p>
          </Example>
          <p>
            Lý do dùng log return: thay đổi của nhiều phiên cộng lại được với nhau, và tăng hay giảm cùng độ lớn được
            đối xử như nhau. Web đổi log return về giá bằng công thức giá sau = giá cuối × e<sup>log return</sup>.
          </p>
        </GuideSection>

        <GuideSection id={GUIDE_ANCHORS.horizon}>
          <p>
            “h” là số <strong>phiên giao dịch</strong> tính từ phiên gần nhất có giá, không phải số ngày lịch. Cuối
            tuần và ngày nghỉ của sàn không tính. Dầu theo lịch giao dịch của sàn CME, vàng và bạc theo lịch của sàn
            NYSE (nơi giao dịch quỹ GLD, SLV).
          </p>
          <Example>
            <p>Giá gần nhất là của phiên thứ Sáu: h = 1 là phiên thứ Hai kế tiếp, h = 5 là phiên thứ Sáu tuần sau.</p>
          </Example>
          <p>
            Càng nhiều phiên, giá càng có thời gian đi xa, nên khoảng dự báo của h = 7 thường rộng hơn h = 1.
          </p>
        </GuideSection>

        <GuideSection id={GUIDE_ANCHORS.quantiles}>
          <p>
            Với mỗi h, dự báo gồm 7 <strong>phân vị</strong> của log return: q05, q10, q25, q50, q75, q90, q95. Phân vị
            là các mốc chia phân phối dự báo từ thấp đến cao; chẳng hạn q10 là mốc mà 10% phân phối dự báo nằm thấp
            hơn nó.
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li>q50 là mức giữa (trung vị): một nửa phân phối dự báo thấp hơn, một nửa cao hơn.</li>
            <li>q10 và q90 là mép dưới và mép trên của khoảng 80%, phần web hiện nhiều nhất.</li>
            <li>q05 và q95 là mép của khoảng 90%, hiện ở quạt log return trong chế độ nâng cao.</li>
          </ul>
          <p>
            Đây là đặc điểm của phân phối dự báo, <strong>chưa phải xác suất đã được kiểm chứng</strong> trên giá thật.
            Giá thật rơi vào khoảng thường xuyên đến đâu được đo riêng ở khối “Độ tin cậy”.
          </p>
        </GuideSection>

        <GuideSection id={GUIDE_ANCHORS.interval}>
          <p>
            <strong>Khoảng 80%</strong> là khoảng từ q10 đến q90. Đó là khoảng mà dự báo đặt ra để chứa giá thật khoảng
            8 trong 10 lần, không phải lời hứa. Web đổi hai mép này ra giá bằng giá cuối × e<sup>q10</sup> và giá cuối ×
            e<sup>q90</sup>; mức giữa dùng q50.
          </p>
          <Example>
            <p>Giá cuối 100, q10 = −2,0%, q50 = +0,2%, q90 = +2,5% (log return).</p>
            <p>Khoảng giá: 100 × e<sup>−0,020</sup> ≈ 98,02 đến 100 × e<sup>0,025</sup> ≈ 102,53; mức giữa ≈ 100,20.</p>
          </Example>
          <p>
            Khoảng rộng nghĩa là thị trường gần đây biến động mạnh, dự báo kém chắc chắn hơn; khoảng hẹp thì ngược lại.
          </p>
        </GuideSection>

        <GuideSection id={GUIDE_ANCHORS.probUp}>
          <p>
            <strong>Xác suất tăng</strong> ước lượng từ 7 phân vị: hệ thống nội suy tuyến tính để tìm phần phân phối
            dự báo nằm trên mức 0% (giá không đổi), rồi làm tròn đến 1%.
          </p>
          <p>
            Số này được giới hạn trong khoảng 5% đến 95%. Lý do: ngoài q05 và q95 không còn phân vị nào để biết phân
            phối đi tiếp ra sao, nên không nói chắc hơn thế. Ở hai đầu, web ghi “≥ 95%” hoặc “≤ 5%”.
          </p>
          <p>
            Nhãn hướng đọc theo con số đã làm tròn: từ 60% là “Nghiêng tăng”, từ 40% trở xuống là “Nghiêng giảm”, còn
            lại là “Chưa rõ xu hướng”, luôn kèm số phiên, ví dụ “Chưa rõ xu hướng · 7 phiên”. Đây cũng là ước lượng của
            dự báo, chưa phải xác suất đã kiểm chứng.
          </p>
        </GuideSection>

        <GuideSection id={GUIDE_ANCHORS.baseline}>
          <p>
            Dự báo hiện dùng <strong>Mốc thống kê 252 phiên</strong> cho cả 4 sản phẩm. Với mỗi h từ 1 đến 7, hệ thống
            lấy các log return h phiên đã xảy ra trong 252 phiên giao dịch gần nhất (khoảng 1 năm), chỉ dùng những
            thay đổi đã hoàn tất trước ngày dự báo, rồi lấy 7 phân vị của chúng.
          </p>
          <p>
            Nói cách khác, khoảng dự báo phản ánh giá đã dao động rộng hẹp ra sao trong năm qua. Cách này chưa dùng mô
            hình học máy và không đọc tin tức; nó không biết trước sự kiện bất thường.
          </p>
        </GuideSection>

        <GuideSection id={GUIDE_ANCHORS.reliability}>
          <p>
            Khối <strong>“Độ tin cậy”</strong> đối chiếu các dự báo đã chạy thật trong 8 tuần gần nhất với giá thực tế
            sau đó. Mỗi cặp là một ngày dự báo và một số phiên h đã có giá thật để chấm.
          </p>
          <dl className="space-y-2">
            {[ACCURACY_METRIC_TEXT.coverage, ACCURACY_METRIC_TEXT.width, ACCURACY_METRIC_TEXT.sign].map((metric) => (
              <div key={metric.name}>
                <dt className="font-medium">{metric.name}</dt>
                <dd className="text-muted">{metric.meaning}</dd>
              </div>
            ))}
          </dl>
          <p>
            Khi chưa đủ số ngày dự báo đã đối chiếu, khối hiện “Đang thu thập (n/m)” thay cho số liệu. Ở chế độ nâng
            cao, mỗi h chỉ hiện số đếm dạng X/Y (số cặp nằm trong khoảng 80% / số cặp đã chấm). Số đo chạy thật này tách
            riêng với kết quả kiểm định lịch sử 2019 ở trang Giới thiệu.
          </p>
        </GuideSection>

        <GuideSection id={GUIDE_ANCHORS.roll}>
          <p>
            Giá dầu Brent và WTI là giá hợp đồng tương lai tháng gần nhất. Khi hợp đồng này đáo hạn, chuỗi giá chuyển
            sang hợp đồng tháng kế tiếp; giá có thể nhảy một bước dù thị trường không thay đổi nhiều.
          </p>
          <p>
            Nếu kỳ dự báo có ngày chuyển hợp đồng, trang sản phẩm hiện nhãn “Đáo hạn hợp đồng” và một dòng lưu ý. Khi
            đó nên đọc khoảng dự báo thận trọng hơn.
          </p>
        </GuideSection>

        <GuideSection id={GUIDE_ANCHORS.sources}>
          <p>{SOURCE_ATTRIBUTION}.</p>
          <ul className="list-disc space-y-1 pl-5">
            <li>Vàng: quỹ GLD; bạc: quỹ SLV (hai quỹ ETF giữ kim loại vật chất).</li>
            <li>Dầu WTI: hợp đồng tương lai CL=F; dầu Brent: hợp đồng tương lai BZ=F.</li>
            <li>Tỷ giá USD/VND: VND=X, chỉ dùng để quy đổi hiển thị.</li>
          </ul>
          <p>
            {config.showMetalPrices
              ? "Giá vàng, bạc là giá quy đổi từ quỹ GLD/SLV (chuỗi đại diện), không phải giá giao ngay."
              : "Vàng và bạc dự báo theo chuỗi đại diện GLD, SLV; web chỉ hiển thị % thay đổi và xác suất tăng, không hiển thị giá."}
          </p>
          <p>
            Dữ liệu là giá cuối phiên, cập nhật mỗi tối thứ Ba đến thứ Bảy (giờ Việt Nam) cho phiên trước đó; không có
            giá trong ngày. Giá chỉ hiện sau khi đăng nhập, và web không có tính năng tải hay xuất dữ liệu giá.
          </p>
        </GuideSection>

        <GuideSection id={GUIDE_ANCHORS.vnd}>
          <p>Giá gốc tính theo USD. Khi chọn VND, web quy đổi theo tỷ giá USD/VND của ngày dự báo (ghi kèm ngày):</p>
          <ul className="list-disc space-y-1 pl-5">
            <li>Dầu: USD/thùng × tỷ giá = VND/thùng.</li>
            <li>
              Vàng, bạc: USD/oz × 37,5 / 31,1034768 × tỷ giá = VND/lượng (1 lượng = 37,5 g, 1 ounce troy = 31,1034768
              g).
            </li>
          </ul>
          <p>{GOLD_VND_NOTE}</p>
          <p>
            Ô “Quy đổi ra số tiền” tính số tiền bạn nhập × e<sup>q</sup> với q là log return h phiên ở q10, q50, q90,
            giả định tỷ giá USD/VND không đổi trong h phiên. Kết quả là giá trị giả định nếu giá thay đổi đúng bằng
            phân vị dự báo, không phải lợi nhuận thực nhận hay được bảo đảm.
          </p>
          <Example>
            <p>
              10.000.000 đồng, q10 = −2,5%, q90 = +3,1% → khoảng 9,75 đến 10,31 triệu đồng sau h phiên.
            </p>
          </Example>
          <p>{AMOUNT_NOTE}</p>
        </GuideSection>

      </article>
    </div>
  );
}
