import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { config } from "../api/config";
import { GUIDE_ANCHORS } from "../components/HowToRead";
import type { GuideAnchor } from "../components/HowToRead";
import { Glossary } from "../components/guide/Glossary";
import {
  BODY_TEXT,
  ChartLegendKey,
  Example,
  HorizonStrip,
  LeanSample,
  MiniFanChart,
  QuestionSection,
  RangeBar,
} from "../components/guide/GuideBlocks";
import { QuickStart } from "../components/guide/QuickStart";
import {
  CollectingExplainer,
  HorizonCountExplainer,
  ReadOneCell,
  ReliabilityMetrics,
} from "../components/guide/ReliabilityGuide";
import { AMOUNT_NOTE } from "../lib/amount";
import { GOLD_VND_NOTE, METAL_PRICE_NOTE, SOURCE_ATTRIBUTION } from "../lib/source";

// Trang "Cách đọc dự báo" cho người không học tài chính hay thống kê: chỉ cách đọc màn hình, ý nghĩa
// từng con số và thuật ngữ; KHÔNG có công thức hay thuật toán của mô hình. Không gọi API, không có giá
// thật (số trong ví dụ là giá giả 100). Lời lẽ theo ADR-0008 và skill forecast-display: khoảng 80% là
// mục tiêu của dự báo, không phải xác suất đã kiểm chứng; không nhắc chỉ số web không hiện.

interface TocGroup {
  title: string;
  items: { id: GuideAnchor; title: string }[];
}

/** Tiêu đề mục = chữ trong mục lục (test kiểm hai chỗ khớp nhau). */
const TITLES: Record<GuideAnchor, string> = {
  [GUIDE_ANCHORS.quickStart]: "Đọc dự báo trong 30 giây",
  [GUIDE_ANCHORS.interval]: "Khoảng 80% là gì?",
  [GUIDE_ANCHORS.probUp]: "Xác suất tăng 53% nghĩa là sao?",
  [GUIDE_ANCHORS.chart]: "Chấm đỏ, dải xanh trên biểu đồ là gì?",
  [GUIDE_ANCHORS.horizon]: "“Phiên” và “sau 7 phiên” là gì?",
  [GUIDE_ANCHORS.reliability]: "Độ tin cậy 8 tuần đọc thế nào?",
  [GUIDE_ANCHORS.sources]: "Vì sao vàng, bạc là giá quy đổi?",
  [GUIDE_ANCHORS.vnd]: "Đổi ra tiền Việt thế nào?",
  [GUIDE_ANCHORS.baseline]: "“Mốc thống kê 252 phiên” là gì?",
  [GUIDE_ANCHORS.roll]: "Nhãn “Đáo hạn hợp đồng” ở dầu là gì?",
  [GUIDE_ANCHORS.modes]: "Chế độ Cơ bản và Nâng cao khác gì?",
  [GUIDE_ANCHORS.quantiles]: "q10, q50, q90 là gì?",
  [GUIDE_ANCHORS.logReturn]: "“Log return” và % thay đổi đọc thế nào?",
  [GUIDE_ANCHORS.glossary]: "Từ điển thuật ngữ",
};

const TOC: TocGroup[] = [
  { title: "Bắt đầu", items: [GUIDE_ANCHORS.quickStart] },
  {
    title: "Trên màn hình dự báo",
    items: [GUIDE_ANCHORS.interval, GUIDE_ANCHORS.probUp, GUIDE_ANCHORS.chart, GUIDE_ANCHORS.horizon],
  },
  { title: "Dự báo có đáng tin?", items: [GUIDE_ANCHORS.reliability] },
  { title: "Giá và tiền", items: [GUIDE_ANCHORS.sources, GUIDE_ANCHORS.vnd] },
  {
    title: "Cho người muốn hiểu thêm",
    items: [
      GUIDE_ANCHORS.baseline,
      GUIDE_ANCHORS.roll,
      GUIDE_ANCHORS.modes,
      GUIDE_ANCHORS.quantiles,
      GUIDE_ANCHORS.logReturn,
    ],
  },
  { title: "Tra cứu", items: [GUIDE_ANCHORS.glossary] },
].map((group) => ({ title: group.title, items: group.items.map((id) => ({ id, title: TITLES[id] })) }));

const ALL_IDS = TOC.flatMap((group) => group.items.map((item) => item.id));
const TOC_ID = "muc-luc";

/** Mục đang đọc (để tô trong mục lục). Không có IntersectionObserver (jsdom) thì bỏ qua. */
function useActiveSection(): GuideAnchor | null {
  const [active, setActive] = useState<GuideAnchor | null>(null);
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((entry) => entry.isIntersecting);
        if (visible.length === 0) return;
        const top = visible.reduce((a, b) => (a.boundingClientRect.top < b.boundingClientRect.top ? a : b));
        setActive(top.target.id as GuideAnchor);
      },
      { rootMargin: "-15% 0px -70% 0px" },
    );
    for (const id of ALL_IDS) {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, []);
  return active;
}

function TableOfContents({ active }: { active: GuideAnchor | null }) {
  // Điện thoại: thu gọn sau nút "Mục lục"; máy tính: luôn mở, dính bên trái khi cuộn
  const [open, setOpen] = useState(false);
  return (
    <nav
      id={TOC_ID}
      aria-label="Mục lục"
      className="scroll-mt-20 rounded-xl border border-line bg-surface lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto lg:border-0 lg:bg-transparent"
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={`${TOC_ID}-list`}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-11 w-full items-center justify-between px-4 text-left text-base font-semibold lg:hidden"
      >
        Mục lục
        <span aria-hidden="true" className={`text-muted motion-safe:transition-transform ${open ? "rotate-180" : ""}`}>
          ▾
        </span>
      </button>
      <p className="hidden text-sm font-semibold lg:block">Mục lục</p>
      <div id={`${TOC_ID}-list`} className={`${open ? "block" : "hidden"} border-t border-line px-4 pb-3 lg:block lg:border-0 lg:px-0`}>
        {TOC.map((group) => (
          <div key={group.title} className="mt-4">
            <p className="text-xs font-medium text-muted">{group.title}</p>
            <ol className="mt-1.5 space-y-0.5">
              {group.items.map((item) => {
                const current = item.id === active;
                return (
                  <li key={item.id}>
                    <a
                      href={`#${item.id}`}
                      onClick={() => setOpen(false)}
                      aria-current={current ? "location" : undefined}
                      className={`-ml-3 block border-l-2 py-1.5 pl-3 text-sm leading-snug motion-safe:transition-colors pointer-coarse:min-h-11 pointer-coarse:py-2.5 ${
                        current
                          ? "border-forecast font-medium text-price"
                          : "border-transparent text-muted hover:border-line hover:text-price"
                      }`}
                    >
                      {item.title}
                    </a>
                  </li>
                );
              })}
            </ol>
          </div>
        ))}
      </div>
    </nav>
  );
}

export default function Guide() {
  const { hash } = useLocation();
  const active = useActiveSection();

  // Router không tự cuộn tới anchor khi đi từ trang khác vào /guide#...
  useEffect(() => {
    if (!hash) return;
    const target = document.getElementById(decodeURIComponent(hash.slice(1)));
    target?.scrollIntoView?.({ block: "start" });
  }, [hash]);

  return (
    <div className="lg:grid lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-x-10">
      <header className="lg:col-start-2 lg:row-start-1">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Cách đọc dự báo</h1>
        <p className={`mt-4 max-w-[40rem] ${BODY_TEXT}`}>
          CPAWS dự báo giá vàng, bạc, dầu Brent và dầu WTI trong 1 đến 7 phiên giao dịch tới. Không ai biết chắc giá
          ngày mai, nên mỗi dự báo là <strong>một khoảng giá kèm xác suất tăng</strong>, không phải một con số chắc
          chắn. Trang này giải thích từng thứ bạn thấy trên màn hình bằng lời thường.
        </p>
        <ul className={`mt-5 flex max-w-[40rem] flex-col gap-2 text-muted ${BODY_TEXT}`}>
          <li>Số trong các ví dụ là số giả (giá 100) để minh họa, không phải giá thật.</li>
          <li>Dự báo có thể sai và không phải lời khuyên mua hay bán.</li>
        </ul>
      </header>

      <div className="mt-8 lg:col-start-1 lg:row-span-2 lg:row-start-1 lg:mt-0">
        <TableOfContents active={active} />
      </div>

      <article className="mt-10 min-w-0 space-y-14 lg:col-start-2 lg:row-start-2">
        <QuickStart />

        <QuestionSection
          id={GUIDE_ANCHORS.interval}
          title={TITLES[GUIDE_ANCHORS.interval]}
          answer="Là khoảng giá mà dự báo đặt ra với mục tiêu chứa giá thật khoảng 8 trong 10 lần."
          aside={
            <Example>
              <p>Giá hôm nay là 100. Dự báo sau 7 phiên: khoảng 80% từ 97 đến 104, mức giữa 100,3.</p>
              <RangeBar low="97" mid="100,3" high="104" now="100" />
            </Example>
          }
          note={
            <>
              “8 trong 10 lần” là mục tiêu của dự báo, <strong>chưa phải xác suất đã được kiểm chứng</strong>. Thực tế
              trúng bao nhiêu lần được đếm riêng ở mục{" "}
              <a href={`#${GUIDE_ANCHORS.reliability}`} className="underline underline-offset-2">
                Độ tin cậy 8 tuần
              </a>
              .
            </>
          }
        >
          <p>
            Thay vì nói “giá sẽ là X”, web đưa ra <strong>mép dưới</strong> và <strong>mép trên</strong>. Cứ khoảng 10
            lần thì có thể có 2 lần giá thật ra ngoài khoảng; điều đó là bình thường.
          </p>
          <p>
            <strong>Mức giữa</strong> là điểm chính giữa của dự báo, không phải giá chắc chắn sẽ đạt.
          </p>
          <p>
            Khoảng <strong>rộng</strong> nghĩa là thời gian gần đây giá lên xuống mạnh, dự báo kém chắc hơn. Khoảng{" "}
            <strong>hẹp</strong> nghĩa là giá đang khá êm.
          </p>
        </QuestionSection>

        <QuestionSection
          id={GUIDE_ANCHORS.probUp}
          title={TITLES[GUIDE_ANCHORS.probUp]}
          answer="Dự báo thấy khả năng giá cao hơn hôm nay chỉ nhỉnh hơn khả năng thấp hơn một chút, gần như 50/50."
          aside={
            <Example>
              <LeanSample percent={53} tone="flat" range="Ở giữa 41% và 59%" />
              <LeanSample percent={64} tone="up" range="Từ 60% trở lên" />
              <LeanSample percent={35} tone="down" range="Từ 40% trở xuống" />
            </Example>
          }
          note="“Nghiêng tăng” không có nghĩa là giá sẽ tăng. Đây là ước lượng của dự báo, chưa phải xác suất đã được kiểm chứng."
        >
          <p>
            Xác suất tăng là khả năng giá sau số phiên đang chọn <strong>cao hơn giá phiên gần nhất</strong>, theo dự
            báo. 50% là hoàn toàn chưa rõ; càng xa 50% thì dự báo càng nghiêng về một phía.
          </p>
          <p>Để đọc nhanh, web gắn nhãn kèm mũi tên và luôn ghi số phiên:</p>
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <span className="font-semibold text-up">▲ Nghiêng tăng</span>: từ 60% trở lên.
            </li>
            <li>
              <span className="font-semibold text-down">▼ Nghiêng giảm</span>: từ 40% trở xuống.
            </li>
            <li>
              <span className="font-semibold text-muted">◆ Chưa rõ xu hướng</span>: ở giữa, như 53%.
            </li>
          </ul>
          <p>Web không bao giờ ghi chắc hơn 95% hay thấp hơn 5%; khi chạm hai đầu, web ghi “≥ 95%” hoặc “≤ 5%”.</p>
        </QuestionSection>

        <QuestionSection
          id={GUIDE_ANCHORS.chart}
          title={TITLES[GUIDE_ANCHORS.chart]}
          answer="Chấm đỏ là mức giữa của dự báo cho từng phiên, không có nghĩa là giảm. Dải xanh là khoảng 80%."
          aside={
            <Example label="Hình minh họa, không phải biểu đồ thật">
              <MiniFanChart />
              <p className="flex justify-between text-sm text-muted">
                <span>Giá đã xảy ra</span>
                <span>7 phiên dự báo</span>
              </p>
            </Example>
          }
        >
          <ChartLegendKey />
          <p>
            Bên trái vạch dọc là giá đã xảy ra; bên phải là 7 phiên dự báo. Dải xanh loe rộng dần vì càng xa càng khó
            đoán. Ở những chỗ khác trên web, tăng và giảm luôn có mũi tên và chữ: ▲ tăng, ▼ giảm.
          </p>
          <p>
            Bấm 1 tháng, 6 tháng, 1 năm hoặc 2 năm để xem xa hơn. Muốn phóng to một đoạn, kéo hai đầu thanh nhỏ dưới
            biểu đồ; bấm “Đặt lại” để về như cũ. Trục giá không bắt đầu từ 0 để thấy rõ lên xuống.
          </p>
        </QuestionSection>

        <QuestionSection
          id={GUIDE_ANCHORS.horizon}
          title={TITLES[GUIDE_ANCHORS.horizon]}
          answer="Một phiên là một ngày sàn giao dịch mở cửa; cuối tuần và ngày lễ của sàn không tính."
          aside={
            <Example>
              <p>Giá gần nhất là của phiên thứ Sáu.</p>
              <HorizonStrip selected={5} />
              <p>“Sau 1 phiên” là thứ Hai kế tiếp; “Sau 5 phiên” là thứ Sáu tuần sau.</p>
            </Example>
          }
          note="Càng nhiều phiên, khoảng dự báo càng rộng. Khoảng của 7 phiên thường rộng hơn khoảng của 1 phiên."
        >
          <p>
            “Sau 7 phiên” nghĩa là sau 7 ngày giao dịch, thường khoảng một tuần rưỡi theo lịch. Trên web, số phiên đôi
            khi được viết tắt là <strong>h</strong> (h = 1…7).
          </p>
          <p>
            Dầu theo lịch của sàn dầu, vàng và bạc theo lịch sàn chứng khoán Mỹ, nên hai nhóm có thể nghỉ khác ngày.
          </p>
        </QuestionSection>

        <section
          id={GUIDE_ANCHORS.reliability}
          aria-labelledby={`${GUIDE_ANCHORS.reliability}-title`}
          className="@container scroll-mt-20 space-y-10 border-t border-line pt-10 lg:scroll-mt-8"
        >
          <div>
            <h2
              id={`${GUIDE_ANCHORS.reliability}-title`}
              className="text-2xl font-semibold tracking-tight sm:text-[1.75rem]"
            >
              {TITLES[GUIDE_ANCHORS.reliability]}
            </h2>
            <div className={`mt-5 max-w-[38rem] space-y-4 ${BODY_TEXT}`}>
              <p className="border-l-4 border-forecast pl-4 text-lg font-semibold leading-snug text-price sm:text-xl">
                Đây là phần chấm điểm: lấy các dự báo đã đưa ra trong 8 tuần gần nhất, so với giá thật xảy ra sau đó.
              </p>
              <p>
                Mỗi lần so là một <strong>cặp</strong>: một ngày dự báo và một số phiên h đã có giá thật. Câu hỏi chính
                là: giá thật có rơi vào khoảng 80% khoảng 8 trong 10 lần không?
              </p>
            </div>
          </div>
          <ReliabilityMetrics />
          <HorizonCountExplainer />
          <div className="max-w-[38rem]">
            <ReadOneCell />
          </div>
          <CollectingExplainer />
          <div className={`max-w-[38rem] rounded-lg bg-warn-bg px-4 py-3 text-warn-fg ${BODY_TEXT}`}>
            <span className="font-semibold">Lưu ý: </span>
            vài tuần đầu số lần còn ít nên tỷ lệ dao động mạnh; đừng kết luận dự báo tốt hay xấu chỉ từ vài tuần. Phần
            chấm 8 tuần là dự báo chạy thật, tách riêng với kiểm định lịch sử 2019 ở trang Giới thiệu.
          </div>
        </section>

        <QuestionSection
          id={GUIDE_ANCHORS.sources}
          title={TITLES[GUIDE_ANCHORS.sources]}
          answer={
            config.showMetalPrices
              ? METAL_PRICE_NOTE
              : "Vàng và bạc dự báo theo chuỗi đại diện GLD, SLV; web chỉ hiển thị % thay đổi và xác suất tăng, không hiển thị giá."
          }
          aside={
            <Example label="Nguồn của từng sản phẩm">
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2">
                <dt className="font-semibold">Vàng</dt>
                <dd>quỹ GLD (chuỗi đại diện)</dd>
                <dt className="font-semibold">Bạc</dt>
                <dd>quỹ SLV (chuỗi đại diện)</dd>
                <dt className="font-semibold">Dầu WTI</dt>
                <dd>hợp đồng tương lai CL=F</dd>
                <dt className="font-semibold">Dầu Brent</dt>
                <dd>hợp đồng tương lai BZ=F</dd>
                <dt className="font-semibold">USD/VND</dt>
                <dd>tỷ giá VND=X, chỉ để đổi sang tiền Việt</dd>
              </dl>
              <p className="text-sm text-muted">{SOURCE_ATTRIBUTION}</p>
            </Example>
          }
        >
          <p>
            GLD và SLV là hai quỹ nắm giữ vàng, bạc thật, có giá đều đặn mỗi phiên. Web theo dõi giá hai quỹ này rồi
            quy về mức tương đương một ounce. Vì vậy giá trên web đi gần giá vàng, bạc thế giới nhưng không trùng khớp.
          </p>
          <p>
            Giá dầu là giá <strong>hợp đồng tương lai</strong>: thỏa thuận mua bán dầu giao vào tháng tới.
          </p>
          <p>
            Dữ liệu là giá cuối phiên, cập nhật mỗi tối thứ Ba đến thứ Bảy (giờ Việt Nam) cho phiên trước đó; không có
            giá trong ngày. Giá chỉ hiện sau khi đăng nhập, và web không có tính năng tải hay xuất dữ liệu giá.
          </p>
        </QuestionSection>

        <QuestionSection
          id={GUIDE_ANCHORS.vnd}
          title={TITLES[GUIDE_ANCHORS.vnd]}
          answer="Bấm nút VND: web đổi giá USD sang tiền Việt theo tỷ giá USD/VND của ngày dự báo, có ghi kèm ngày."
          aside={
            <Example>
              <p>
                Ô “Quy đổi ra số tiền”: bạn nhập 10.000.000 đồng, khoảng 80% sau 7 phiên là từ −2,5% đến +3,1%.
              </p>
              <p className="text-lg font-semibold">Khoảng 9,75 đến 10,31 triệu đồng</p>
              <p className="text-sm text-muted">Nếu giá đi đúng mép dưới hoặc mép trên của dự báo.</p>
            </Example>
          }
          note={AMOUNT_NOTE}
        >
          <p>Dầu hiện theo đồng/thùng. Vàng, bạc hiện theo đồng/lượng (1 lượng = 37,5 gam, khoảng 1,2 ounce).</p>
          <p>{GOLD_VND_NOTE}</p>
          <p>
            Ô <strong>“Quy đổi ra số tiền”</strong>: bạn nhập một số tiền, web cho biết số tiền đó sẽ thành bao nhiêu
            nếu giá đi đúng mép dưới, mức giữa hoặc mép trên của dự báo. Đây chỉ là giá trị giả định, giả định tỷ giá
            không đổi; không phải lợi nhuận thực nhận hay được bảo đảm.
          </p>
        </QuestionSection>

        <QuestionSection
          id={GUIDE_ANCHORS.baseline}
          title={TITLES[GUIDE_ANCHORS.baseline]}
          answer="Là cách dự báo hiện tại: dựa vào mức giá đã lên xuống trong khoảng 1 năm giao dịch gần nhất (252 phiên)."
        >
          <p>
            Năm qua giá dao động mạnh thì khoảng dự báo rộng; năm qua êm thì khoảng hẹp. Cách này chưa dùng mô hình học
            máy và không đọc tin tức, nên không biết trước sự kiện bất ngờ.
          </p>
          <p>
            Mỗi dự báo trên web đều ghi nhãn <strong>Mốc thống kê 252 phiên</strong> để bạn biết dự báo đến từ đâu.
          </p>
        </QuestionSection>

        <QuestionSection
          id={GUIDE_ANCHORS.roll}
          title={TITLES[GUIDE_ANCHORS.roll]}
          answer="Giá dầu có thể nhảy một bước vì chuyển sang hợp đồng tháng sau, không hẳn vì thị trường biến động."
        >
          <p>
            Giá dầu trên web là giá hợp đồng giao tháng gần nhất. Khi hợp đồng này hết hạn, chuỗi giá chuyển sang hợp
            đồng tháng kế tiếp, vốn có giá hơi khác. Nếu việc chuyển này rơi vào 7 phiên dự báo, trang sản phẩm hiện nhãn
            “Đáo hạn hợp đồng” và một dòng lưu ý; khi đó nên đọc khoảng dự báo thận trọng hơn.
          </p>
        </QuestionSection>

        <QuestionSection
          id={GUIDE_ANCHORS.modes}
          title={TITLES[GUIDE_ANCHORS.modes]}
          answer="Cơ bản đủ để đọc nhanh. Nâng cao hiện thêm bảng số chi tiết cho người muốn xem kỹ."
        >
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <strong>Cơ bản</strong>: xác suất tăng, khoảng giá 80%, biểu đồ giá và dự báo, quy đổi ra số tiền, khối
              Độ tin cậy.
            </li>
            <li>
              <strong>Nâng cao</strong>: thêm bảng q10, q50, q90 cho từng phiên, biểu đồ quạt % thay đổi, và bảng
              “Trong khoảng 80%” theo h ở trang Độ chính xác.
            </li>
          </ul>
          <p>Nút chuyển ở góc trên trang sản phẩm; web nhớ lựa chọn của bạn.</p>
        </QuestionSection>

        <QuestionSection
          id={GUIDE_ANCHORS.quantiles}
          title={TITLES[GUIDE_ANCHORS.quantiles]}
          answer="Là tên kỹ thuật của mép dưới (q10), mức giữa (q50) và mép trên (q90) của khoảng 80%."
          aside={
            <Example label="Thứ tự các mốc, từ thấp đến cao">
              <ol className="tabular grid grid-cols-7 gap-1 text-center text-sm">
                {["q05", "q10", "q25", "q50", "q75", "q90", "q95"].map((name) => (
                  <li
                    key={name}
                    className={`rounded-md py-2 ${
                      name === "q10" || name === "q90"
                        ? "bg-band font-semibold"
                        : name === "q50"
                          ? "bg-price font-semibold text-on-price"
                          : "bg-surface text-muted ring-1 ring-line"
                    }`}
                  >
                    {name}
                  </li>
                ))}
              </ol>
              <p className="text-sm text-muted">Web hiện nhiều nhất ba mốc tô đậm: q10, q50, q90.</p>
            </Example>
          }
        >
          <p>
            Dự báo gồm 7 mốc xếp từ thấp đến cao. Số sau chữ q cho biết mốc đứng ở đâu: q10 gần đáy, q50 ở giữa, q90
            gần đỉnh. q05 và q95 là mép của một khoảng rộng hơn (khoảng 90%), hiện nhạt hơn trên biểu đồ quạt.
          </p>
          <p>Đây là các mốc của dự báo, chưa phải xác suất đã được kiểm chứng.</p>
        </QuestionSection>

        <QuestionSection
          id={GUIDE_ANCHORS.logReturn}
          title={TITLES[GUIDE_ANCHORS.logReturn]}
          answer="Đọc như % thay đổi so với giá phiên gần nhất: +1,0% là cao hơn khoảng 1%, −2,0% là thấp hơn khoảng 2%."
          aside={
            <Example>
              <p>Giá phiên gần nhất là 100.</p>
              <ul className="space-y-1">
                <li>
                  <span className="font-semibold text-up">▲ +2,0%</span> → giá khoảng 102
                </li>
                <li>
                  <span className="font-semibold text-down">▼ −1,0%</span> → giá khoảng 99
                </li>
              </ul>
            </Example>
          }
        >
          <p>
            “Log return” là tên kỹ thuật mà các bảng ở chế độ Nâng cao dùng. Với mức thay đổi nhỏ như trên web, nó gần
            như bằng % thay đổi quen thuộc, nên bạn cứ đọc như %.
          </p>
          <p>
            Trên <strong>biểu đồ quạt</strong>, trục ngang là số phiên tới, trục dọc là % thay đổi; đường 0% là giá
            không đổi. Quạt loe ra vì càng xa càng khó đoán.
          </p>
        </QuestionSection>

        <Glossary />
      </article>
    </div>
  );
}
