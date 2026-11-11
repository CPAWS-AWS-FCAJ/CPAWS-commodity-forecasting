import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import About from "./About";
import AssetPage from "./AssetPage";
import Home from "./Home";
import { SettingsProvider } from "../lib/settings";
import { SOURCE_ATTRIBUTION } from "../lib/source";

const flags = vi.hoisted(() => ({ show: true }));
vi.mock("../api/config", () => ({
  config: {
    apiUrl: "",
    useSample: true,
    historyAvailable: true,
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

function mount(path: string, mode: "basic" | "advanced", currency: "USD" | "VND" = "USD") {
  window.localStorage.setItem("cpaws.mode", mode);
  window.localStorage.setItem("cpaws.currency", currency);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SettingsProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route index element={<Home />} />
            <Route path="asset/:id" element={<AssetPage />} />
            <Route path="about" element={<About />} />
          </Routes>
        </MemoryRouter>
      </SettingsProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => cleanup());

describe("trang sản phẩm và trang chủ với cờ VITE_SHOW_METAL_PRICES", () => {
  it("vàng, cờ tắt, cơ bản: không giá, không nút VND, có quạt return", async () => {
    flags.show = false;
    mount("/asset/gold", "basic");
    expect((await screen.findAllByText(/đang được ẩn/)).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "VND" })).toBeNull();
    expect(screen.queryByText(/Giá thực tế và dự báo/)).toBeNull();
    expect(screen.queryByText(/Giá cuối ngày .* tỷ giá USD\/VND/)).toBeNull();
    expect(screen.getAllByText(/Quạt log return/)).toHaveLength(1);
    expect(screen.getByText(/mức thay đổi nhiều khả năng/)).toBeInTheDocument();
  });

  it("vàng, cờ tắt, nâng cao: đúng 1 quạt return, bảng không có cột giá", async () => {
    flags.show = false;
    mount("/asset/gold", "advanced");
    expect((await screen.findAllByText(/đang được ẩn/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Quạt log return/)).toHaveLength(1);
    expect(screen.queryByText("Giá q10–q90")).toBeNull();
    expect(screen.getByText("Phân vị của log return")).toBeInTheDocument();
  });

  it("vàng, cờ bật: vẫn hiện giá, nút VND và biểu đồ giá", async () => {
    flags.show = true;
    mount("/asset/gold", "basic");
    expect(await screen.findByText(/Giá thực tế và dự báo/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "VND" })).toBeInTheDocument();
    expect(screen.getByText(/Giá cuối ngày .* tỷ giá USD\/VND/)).toBeInTheDocument();
    expect(screen.queryAllByText(/đang được ẩn/)).toHaveLength(0);
  });

  it("dầu WTI, cờ tắt: vẫn hiện giá", async () => {
    flags.show = false;
    mount("/asset/wti", "basic");
    expect(await screen.findByText(/Giá thực tế và dự báo/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "VND" })).toBeInTheDocument();
  });

  it("dải 7 thẻ h = 1…7; bấm thẻ h = 5 thì phần tóm tắt đổi theo", async () => {
    flags.show = false;
    mount("/asset/wti", "basic");
    const cards = await screen.findAllByRole("button", { name: /^Sau \d phiên:/ });
    expect(cards.map((card) => card.getAttribute("aria-label")?.match(/^Sau (\d)/)?.[1])).toEqual([
      "1", "2", "3", "4", "5", "6", "7",
    ]);
    expect(cards[6]).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(cards[4]);
    expect(cards[4]).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Sau 5 phiên, nhiều khả năng/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "7 phiên" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "1 phiên" }));
    expect(cards[0]).toHaveAttribute("aria-pressed", "true");
  });

  it("khối quy đổi ra số tiền có ở vàng (cờ tắt, cả hai chế độ) và dầu; đi theo h đang chọn", async () => {
    flags.show = false;
    mount("/asset/gold", "basic");
    expect(await screen.findByLabelText("Số tiền (đồng)")).toBeInTheDocument();
    cleanup();
    mount("/asset/gold", "advanced");
    expect(await screen.findByLabelText("Số tiền (đồng)")).toBeInTheDocument();
    cleanup();
    mount("/asset/wti", "basic");
    fireEvent.change(await screen.findByLabelText("Số tiền (đồng)"), { target: { value: "10.000.000" } });
    expect(screen.getByText(/sau 7 phiên \(phiên/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "3 phiên" }));
    expect(screen.getByText(/sau 3 phiên \(phiên/)).toBeInTheDocument();
  });

  it("vàng, cờ tắt: thẻ chỉ có %, không có đơn vị giá", async () => {
    flags.show = false;
    mount("/asset/gold", "basic");
    const cards = await screen.findAllByRole("button", { name: /^Sau \d phiên:/ });
    expect(cards).toHaveLength(7);
    for (const card of cards) expect(card.textContent).not.toMatch(/USD|VND/);
  });

  it("trang chủ, cờ tắt: vàng/bạc ẩn giá, dầu giữ giá", async () => {
    flags.show = false;
    mount("/", "basic");
    expect((await screen.findAllByText(/Thay đổi 80% sau 7 phiên/)).length).toBe(2);
    expect(screen.getAllByText(/Khoảng giá 80% sau 7 phiên/).length).toBe(2);
  });
});

describe("dòng nguồn dữ liệu và nhãn vàng VND/lượng (ADR-0005)", () => {
  const GOLD_VND = /giá thế giới quy đổi, không phải giá vàng miếng trong nước/;

  it("trang chủ có dòng nguồn", async () => {
    flags.show = true;
    mount("/", "basic");
    expect(await screen.findByText(SOURCE_ATTRIBUTION)).toBeInTheDocument();
  });

  it.each(["gold", "silver", "brent", "wti"])("trang %s có dòng nguồn", async (asset) => {
    flags.show = true;
    mount(`/asset/${asset}`, "basic");
    expect(await screen.findByText(SOURCE_ATTRIBUTION)).toBeInTheDocument();
  });

  it("trang Giới thiệu có dòng nguồn và câu giá thế giới quy đổi", () => {
    flags.show = true;
    mount("/about", "basic");
    expect(screen.getByText(/Nguồn: Yahoo Finance, U\.S\. EIA/)).toBeInTheDocument();
    expect(screen.getByText(GOLD_VND)).toBeInTheDocument();
  });

  it("vàng theo VND: tóm tắt và phần lưu ý đều có nhãn giá thế giới quy đổi", async () => {
    flags.show = true;
    mount("/asset/gold", "advanced", "VND");
    expect((await screen.findAllByText(GOLD_VND)).length).toBe(2);
  });

  it("vàng theo USD và dầu theo VND: không có nhãn vàng miếng", async () => {
    flags.show = true;
    mount("/asset/gold", "basic", "USD");
    await screen.findByText(SOURCE_ATTRIBUTION);
    expect(screen.queryAllByText(GOLD_VND)).toHaveLength(0);
    cleanup();
    mount("/asset/brent", "basic", "VND");
    await screen.findByText(SOURCE_ATTRIBUTION);
    expect(screen.queryAllByText(GOLD_VND)).toHaveLength(0);
  });

  it("vàng, cờ tắt: vẫn có dòng nguồn, không có nhãn VND", async () => {
    flags.show = false;
    mount("/asset/gold", "basic", "VND");
    expect(await screen.findByText(SOURCE_ATTRIBUTION)).toBeInTheDocument();
    expect(screen.queryAllByText(GOLD_VND)).toHaveLength(0);
  });
});
