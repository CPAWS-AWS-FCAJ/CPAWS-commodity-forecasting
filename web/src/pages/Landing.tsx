import { Link } from "react-router-dom";
import { config } from "../api/config";
import { ASSET_IDS } from "../api/types";
import { signInPath } from "../auth/redirect";
import { DISCLAIMER_TEXT } from "../components/Disclaimer";
import { LockMark } from "../components/shell/LockMark";
import { PRIMARY_BUTTON, PublicShell, SECONDARY_BUTTON } from "../components/shell/PublicChrome";
import { ASSET_DOT_CLASS, ASSETS } from "../lib/assets";
import { SOURCE_ATTRIBUTION } from "../lib/source";

// Trang giới thiệu công khai (chưa đăng nhập). ADR-0005: không có con số giá hay dự báo nào ở đây,
// không gọi API dự báo; giá chỉ hiện sau đăng nhập.

const STEPS = [
  {
    title: "Lấy giá mỗi tối",
    text: "Khoảng 19:15 giờ Việt Nam, thứ Ba đến thứ Bảy, hệ thống lấy giá đóng cửa của phiên gần nhất từ Yahoo Finance và đối chiếu với U.S. EIA.",
  },
  {
    title: "Tính khoảng theo mốc thống kê 252 phiên",
    text: "Từ biến động 1–7 phiên trong 252 phiên giao dịch gần nhất (khoảng một năm), hệ thống lấy 7 phân vị. Web hiện khoảng 80% (q10–q90) và trung vị.",
  },
  {
    title: "Quy đổi ra giá và xác suất tăng",
    text: "Khoảng dự báo được quy đổi ra giá theo USD hoặc VND, kèm xác suất giá tăng và nhãn hướng luôn ghi số phiên.",
  },
  {
    title: "Chatbot giải thích, có trích nguồn",
    text: "Chatbot tiếng Việt lấy con số từ chính dự báo, nêu lý do kèm nguồn như thông cáo của Fed và báo cáo của EIA, không tư vấn đầu tư.",
  },
] as const;

/** Sơ đồ cách đọc một dự báo: giá đã qua, dải khoảng 80% mở rộng dần, trung vị nét đứt. Không có số. */
function FanIllustration() {
  return (
    <svg
      viewBox="0 36 520 264"
      role="img"
      aria-labelledby="fan-title fan-desc"
      className="h-auto w-full"
    >
      <title id="fan-title">Hình minh họa cách đọc một dự báo</title>
      <desc id="fan-desc">
        Đường giá đã qua đến hôm nay, sau đó là dải khoảng 80% mở rộng dần qua 7 phiên tới, đường trung
        vị nét đứt nằm trong dải. Hình minh họa, không phải dữ liệu thật.
      </desc>
      {/* Dải khoảng 80% (q10–q90) */}
      <path
        d="M272 132 C 330 112 400 92 456 70 L 456 206 C 400 186 330 158 272 132 Z"
        fill="var(--color-band)"
      />
      {/* Trung vị q50 */}
      <path
        d="M272 132 C 330 128 400 126 456 124"
        fill="none"
        stroke="var(--color-forecast)"
        strokeWidth="2"
        strokeDasharray="6 5"
      />
      {/* Giá đã qua */}
      <polyline
        points="24,156 48,148 72,158 96,142 120,150 144,134 168,142 192,128 216,138 240,124 272,132"
        fill="none"
        stroke="var(--color-price)"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <circle cx="272" cy="132" r="4" fill="var(--color-price)" />
      {/* Trục và mốc hôm nay */}
      <line x1="24" y1="246" x2="456" y2="246" stroke="var(--color-line)" strokeWidth="1" />
      <line x1="272" y1="40" x2="272" y2="246" stroke="var(--color-muted)" strokeWidth="1" strokeDasharray="3 4" />
      {[1, 2, 3, 4, 5, 6, 7].map((k) => (
        <line
          key={k}
          x1={272 + (k * 184) / 7}
          y1="246"
          x2={272 + (k * 184) / 7}
          y2="252"
          stroke="var(--color-muted)"
          strokeWidth="1"
        />
      ))}
      {/* Màn hẹp: hình thu nhỏ còn ~60%, nên tăng cỡ chữ trong hình để chữ hiển thị ~12 px */}
      <g fontSize="13" fill="var(--color-muted)" className="max-sm:text-[20px]">
        <text x="272" y="270" textAnchor="middle">
          hôm nay
        </text>
        <text x="456" y="270" textAnchor="middle">
          7 phiên tới
        </text>
        <text x="24" y="270">
          phiên đã qua
        </text>
        <text x="464" y="74">q90</text>
        <text x="464" y="128">q50</text>
        <text x="464" y="210">q10</text>
      </g>
      <g fontSize="13" fill="var(--color-price)" className="max-sm:text-[20px]">
        <text x="24" y="132">Giá đã qua</text>
        <text x="368" y="168">Khoảng 80%</text>
        <text x="384" y="116" className="max-sm:hidden">
          Trung vị
        </text>
        {/* Chữ to hơn trên màn hẹp: dời nhãn sang trái để không chạm "q50" */}
        <text x="296" y="118" className="sm:hidden">
          Trung vị
        </text>
      </g>
      {/* Màn hẹp: chú thích này chuyển ra figcaption HTML bên dưới hình (đủ cỡ chữ, không sát trục) */}
      <text x="24" y="292" fontSize="12" fill="var(--color-muted)" className="max-sm:hidden">
        Hình minh họa, không phải dữ liệu thật
      </text>
    </svg>
  );
}

export default function Landing() {
  const signUp = config.allowSignUp;
  return (
    <PublicShell footerDisclaimer={false}>
      {/* Mở đầu: nói rõ sản phẩm làm gì, một hành động chính */}
      <section className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-14 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:px-10 lg:py-20">
        <div className="transition-[opacity,translate] duration-300 ease-out starting:translate-y-2 starting:opacity-0 motion-reduce:transition-none">
          <h1 className="max-w-xl text-4xl font-semibold leading-[1.1] tracking-tight [overflow-wrap:break-word] sm:text-5xl">
            Dự báo khoảng giá vàng, bạc và dầu cho 1–7 phiên tới
          </h1>
          <p className="mt-5 max-w-lg text-base text-muted sm:text-lg">
            Mỗi tối CPAWS cập nhật giá đóng cửa, tính khoảng giá nhiều khả năng và xác suất tăng, rồi để
            chatbot tiếng Việt giải thích kèm nguồn.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to={signInPath()} className={PRIMARY_BUTTON}>
              Đăng nhập để xem dự báo
            </Link>
            {signUp ? (
              <Link to={signInPath(undefined, { signUp: true })} className={SECONDARY_BUTTON}>
                Tạo tài khoản
              </Link>
            ) : null}
          </div>
          <dl className="mt-10 grid max-w-lg grid-cols-3 gap-4 border-t border-line pt-5 text-sm">
            <div>
              <dt className="text-muted">Theo dõi</dt>
              <dd className="mt-1 font-medium">4 sản phẩm</dd>
            </div>
            <div>
              <dt className="text-muted">Hiển thị</dt>
              <dd className="mt-1 font-medium">USD và VND</dd>
            </div>
            <div>
              <dt className="text-muted">Cập nhật</dt>
              <dd className="mt-1 font-medium">Tối thứ Ba–thứ Bảy</dd>
            </div>
          </dl>
        </div>
        <figure className="rounded-lg border border-line bg-surface p-4 sm:p-6">
          <FanIllustration />
          <figcaption className="mt-2 text-xs text-muted sm:hidden">Hình minh họa, không phải dữ liệu thật</figcaption>
        </figure>
      </section>

      {/* Bốn sản phẩm: chỉ tên và chuỗi theo dõi, không có giá */}
      <section aria-labelledby="landing-assets" className="border-t border-line bg-surface">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-14 sm:px-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:px-10 lg:py-20">
          <div>
            <h2 id="landing-assets" className="text-2xl font-semibold tracking-tight sm:text-3xl">
              Bốn sản phẩm theo dõi
            </h2>
            <p className="mt-3 max-w-md text-muted">
              Mỗi sản phẩm có một màu nhận diện, dùng giống nhau ở mọi trang và biểu đồ. Giá và khoảng
              dự báo chỉ hiện sau khi đăng nhập.
            </p>
          </div>
          <ul className="divide-y divide-line border-y border-line">
            {ASSET_IDS.map((id) => (
              <li key={id} className="flex items-center gap-4 py-4">
                <span aria-hidden="true" className={`size-3 shrink-0 rounded-full ${ASSET_DOT_CLASS[id]}`} />
                <span className="w-28 shrink-0 font-medium">{ASSETS[id].name}</span>
                <span className="min-w-0 text-sm text-muted">{ASSETS[id].seriesLabel}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Cách hệ thống tạo dự báo */}
      <section aria-labelledby="landing-steps" className="border-t border-line">
        <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6 lg:px-10 lg:py-20">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <h2 id="landing-steps" className="text-2xl font-semibold tracking-tight sm:text-3xl">
              Cách hệ thống tạo dự báo
            </h2>
            <Link
              to="/guide"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-forecast underline-offset-4 hover:underline pointer-coarse:min-h-11"
            >
              Xem cách đọc dự báo
              {/* Landing chỉ hiện khi chưa đăng nhập; /guide cần đăng nhập */}
              <LockMark />
            </Link>
          </div>
          <ol className="mt-8 grid gap-x-10 gap-y-8 md:grid-cols-2">
            {STEPS.map((step, index) => (
              <li key={step.title} className="grid grid-cols-[2rem_minmax(0,1fr)] gap-3">
                <span
                  aria-hidden="true"
                  className="tabular flex size-8 items-center justify-center rounded-full border border-line text-sm font-medium text-muted"
                >
                  {index + 1}
                </span>
                <div>
                  <h3 className="font-medium">{step.title}</h3>
                  <p className="mt-1 max-w-prose text-sm text-muted">{step.text}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Kết: câu miễn trừ đúng nguyên văn, nguồn dữ liệu, hành động chính */}
      <section className="border-t border-line bg-surface">
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-12 sm:px-6 md:flex-row md:items-center md:justify-between lg:px-10">
          <div>
            <p className="text-lg font-medium">{DISCLAIMER_TEXT}</p>
            <p className="mt-2 text-sm text-muted">
              {SOURCE_ATTRIBUTION}. Web không có tính năng tải hay xuất dữ liệu giá.
            </p>
          </div>
          <Link to={signInPath()} className={PRIMARY_BUTTON}>
            Đăng nhập để xem dự báo
          </Link>
        </div>
      </section>
    </PublicShell>
  );
}
