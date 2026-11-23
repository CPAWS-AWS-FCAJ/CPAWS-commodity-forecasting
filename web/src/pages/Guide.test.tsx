import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { GUIDE_ANCHORS } from "../components/HowToRead";
import { filterGlossary, foldText, GLOSSARY } from "../components/guide/glossaryTerms";
import { ACCURACY_METRIC_TEXT } from "../lib/accuracy";
import { AMOUNT_NOTE } from "../lib/amount";
import { GOLD_VND_NOTE, METAL_PRICE_NOTE, SOURCE_ATTRIBUTION } from "../lib/source";
import Guide from "./Guide";

const flags = vi.hoisted(() => ({ show: true }));
vi.mock("../api/config", () => ({
  config: {
    apiUrl: "",
    useSample: true,
    sampleAccuracy: "collecting",
    accuracyApiEnabled: true,
    get showMetalPrices() {
      return flags.show;
    },
    authEnabled: false,
    region: "ap-southeast-1",
    userPoolId: "",
    userPoolClientId: "",
  },
}));

// Không bọc QueryClientProvider: trang hướng dẫn không được gọi API.
function mount(path = "/guide") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Guide />
    </MemoryRouter>,
  );
}

afterEach(() => cleanup());

describe("trang Cách đọc dự báo", () => {
  it("có tiêu đề, mục lục và đủ các anchor mà trang khác link tới", () => {
    flags.show = true;
    mount();
    expect(screen.getByRole("heading", { level: 1, name: "Cách đọc dự báo" })).toBeInTheDocument();
    const toc = screen.getByRole("navigation", { name: "Mục lục" });
    for (const anchor of Object.values(GUIDE_ANCHORS)) {
      expect(document.getElementById(anchor)).not.toBeNull();
      expect(within(toc).getByRole("link", { name: document.getElementById(`${anchor}-title`)!.textContent! })).toHaveAttribute(
        "href",
        `#${anchor}`,
      );
    }
  });

  it("các id anchor cũ không đổi (FanChart, HorizonCards, ReliabilityBlock, AssetPage… link tới)", () => {
    expect(GUIDE_ANCHORS).toMatchObject({
      chart: "doc-bieu-do",
      logReturn: "log-return",
      horizon: "so-phien",
      quantiles: "phan-vi",
      interval: "khoang-80",
      probUp: "xac-suat-tang",
      baseline: "moc-252",
      reliability: "do-tin-cay",
      roll: "dao-han",
      sources: "nguon-du-lieu",
      vnd: "quy-doi-vnd",
    });
  });

  it("mở đầu bằng phần đọc nhanh 4 bước", () => {
    flags.show = true;
    mount();
    const quick = document.getElementById(GUIDE_ANCHORS.quickStart)!;
    expect(within(quick).getByRole("heading", { name: "Đọc dự báo trong 30 giây" })).toBeInTheDocument();
    expect(within(quick).getAllByRole("listitem")).toHaveLength(4);
  });

  it("giải thích đúng khái niệm, đúng nhãn và câu bắt buộc", () => {
    flags.show = true;
    mount();
    const text = document.body.textContent ?? "";
    expect(text).toContain("Mốc thống kê 252 phiên");
    expect(text).toContain("chưa phải xác suất đã được kiểm chứng");
    expect(text).toContain("không có nghĩa là giảm");
    expect(text).toContain("“≥ 95%” hoặc “≤ 5%”");
    expect(text).toContain("Nghiêng tăng");
    expect(text).toContain("Chưa rõ xu hướng");
    expect(text).toContain(AMOUNT_NOTE);
    expect(text).toContain(SOURCE_ATTRIBUTION);
    expect(text).toContain(METAL_PRICE_NOTE);
    expect(text).toContain("giá quy đổi từ quỹ GLD/SLV (chuỗi đại diện), không phải giá giao ngay");
    expect(text).toContain(GOLD_VND_NOTE);
    expect(text).toContain("không phải giá vàng miếng trong nước");
    expect(text).toContain("không có tính năng tải hay xuất dữ liệu giá");
    // Mọi ví dụ có số đều ghi rõ là minh họa
    expect(screen.getAllByText(/^Ví dụ minh họa/).length).toBeGreaterThanOrEqual(5);
  });

  it("độ tin cậy: giải thích X/Y theo h, mục tiêu 8/10, Y giảm theo h, đang thu thập", () => {
    flags.show = true;
    mount();
    const section = document.getElementById(GUIDE_ANCHORS.reliability)!;
    const text = section.textContent ?? "";
    expect(text).toContain("Trong khoảng 80%");
    expect(text).toMatch(/Y thường ít hơn ở h lớn, nhưng không nhất thiết giảm đều/);
    expect(text).toContain("khoảng 8 phần 10");
    expect(text).toContain("10/16");
    expect(text).toContain("Đang thu thập (16/20)");
    expect(text).toContain("chưa đủ ngày nên chưa kết luận");
    for (const metric of Object.values(ACCURACY_METRIC_TEXT)) expect(text).toContain(metric.name);
    expect(text).toContain("không xem chênh lệch giữa chúng là mức cải thiện");
  });

  it("không có công thức, thuật toán mô hình hay số giá thật", () => {
    flags.show = true;
    mount();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/pinball|nội suy|ln\(|exp\(|e\^|logarit|phân vị thực nghiệm|nhân quả/i);
    expect(text).not.toMatch(/31,1034768/);
    // không có con số đi kèm đơn vị giá
    expect(text).not.toMatch(/\d[\d.,]*\s*(USD|VND)\s*\/\s*(oz|thùng|lượng)/);
    expect(text).not.toMatch(/\d[\d.,]*\s*USD\b/);
    // không diễn đạt q10/q90 như xác suất đã kiểm chứng, không hứa hẹn
    expect(text).not.toMatch(/10% khả năng/);
    expect(text).not.toMatch(/chắc chắn (tăng|giảm)|bảo đảm lợi nhuận|thời gian thực/i);
    expect(text).not.toMatch(/MAPE|RMSE|Brier|MASE/);
    expect(document.querySelector("sup")).toBeNull();
  });

  it("từ điển: lọc nhanh không phân biệt dấu, báo khi không có từ khớp", () => {
    flags.show = true;
    mount();
    const glossary = document.getElementById(GUIDE_ANCHORS.glossary)!;
    const input = within(glossary).getByRole("searchbox", { name: "Tìm từ" });
    fireEvent.change(input, { target: { value: "dao han" } });
    expect(within(glossary).getByText("Đáo hạn hợp đồng")).toBeInTheDocument();
    expect(within(glossary).queryByText("Xác suất tăng")).toBeNull();
    fireEvent.change(input, { target: { value: "zzzz" } });
    expect(within(glossary).getByRole("status")).toHaveTextContent("Không có từ nào khớp");
  });

  it("mục lục trên điện thoại thu gọn sau nút", () => {
    flags.show = true;
    mount();
    const toggle = screen.getByRole("button", { name: /Mục lục/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("cờ VITE_SHOW_METAL_PRICES tắt: nói rõ vàng, bạc chỉ hiện % thay đổi", () => {
    flags.show = false;
    mount();
    expect(screen.getByText(/web chỉ hiển thị % thay đổi và xác suất tăng, không hiển thị giá/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(METAL_PRICE_NOTE);
  });

  it("vào thẳng /guide#anchor thì cuộn tới mục đó", () => {
    flags.show = true;
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    mount(`/guide#${GUIDE_ANCHORS.reliability}`);
    expect(scroll).toHaveBeenCalled();
    expect(scroll.mock.contexts[0]).toBe(document.getElementById(GUIDE_ANCHORS.reliability));
  });
});

describe("từ điển thuật ngữ", () => {
  it("mỗi định nghĩa tối đa 2 câu, không trùng từ", () => {
    const terms = GLOSSARY.flatMap((group) => group.terms);
    expect(new Set(terms.map((item) => item.term)).size).toBe(terms.length);
    for (const item of terms) {
      const sentences = item.definition.split(/(?<=[.?!])\s+(?=[A-ZÀ-Ỹ“])/u);
      expect(sentences.length, item.term).toBeLessThanOrEqual(2);
    }
  });

  it("foldText bỏ dấu và chữ hoa", () => {
    expect(foldText("Đáo Hạn")).toBe("dao han");
    expect(filterGlossary("khoang 80").flatMap((group) => group.terms).length).toBeGreaterThan(0);
  });
});
