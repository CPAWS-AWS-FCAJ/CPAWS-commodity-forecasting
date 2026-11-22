import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { GUIDE_ANCHORS } from "../components/HowToRead";
import { AMOUNT_NOTE } from "../lib/amount";
import { SOURCE_ATTRIBUTION } from "../lib/source";
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
  it("có tiêu đề, mục lục và đủ các anchor mà trang sản phẩm link tới", () => {
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

  it("giải thích đúng khái niệm, đúng nhãn và câu bắt buộc", () => {
    flags.show = true;
    mount();
    const text = document.body.textContent ?? "";
    expect(text).toContain("Mốc thống kê 252 phiên");
    expect(text).toContain("chưa phải xác suất đã được kiểm chứng");
    expect(text).toContain("không có nghĩa là giảm");
    expect(text).toMatch(/5% đến 95%/);
    expect(text).toContain("“≥ 95%” hoặc “≤ 5%”");
    expect(text).toContain("37,5 / 31,1034768");
    expect(screen.getByText(AMOUNT_NOTE)).toBeInTheDocument();
    expect(text).toContain(SOURCE_ATTRIBUTION);
    expect(text).toContain("giá quy đổi từ quỹ GLD/SLV (chuỗi đại diện), không phải giá giao ngay");
    expect(text).toContain("không phải giá vàng miếng trong nước");
  });

  it("không chứa số giá thật, không hứa hẹn, không dùng chỉ số web không hiện", () => {
    flags.show = true;
    mount();
    const text = document.body.textContent ?? "";
    // không có con số đi kèm đơn vị giá
    expect(text).not.toMatch(/\d[\d.,]*\s*(USD|VND)\s*\/\s*(oz|thùng|lượng)/);
    expect(text).not.toMatch(/\d[\d.,]*\s*USD\b/);
    // không diễn đạt q10/q90 như xác suất đã kiểm chứng
    expect(text).not.toMatch(/10% khả năng/);
    expect(text).not.toMatch(/chắc chắn (tăng|giảm)|bảo đảm lợi nhuận|thời gian thực/i);
    expect(text).not.toMatch(/pinball|MAPE|RMSE|Brier|MASE/);
  });

  it("cờ VITE_SHOW_METAL_PRICES tắt: nói rõ vàng, bạc chỉ hiện % thay đổi", () => {
    flags.show = false;
    mount();
    expect(screen.getByText(/web chỉ hiển thị % thay đổi và xác suất tăng, không hiển thị giá/)).toBeInTheDocument();
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
