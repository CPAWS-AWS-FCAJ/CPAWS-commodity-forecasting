import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import AssetPage from "./AssetPage";
import Home from "./Home";
import { SettingsProvider } from "../lib/settings";

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

function mount(path: string, mode: "basic" | "advanced") {
  window.localStorage.setItem("cpaws.mode", mode);
  window.localStorage.setItem("cpaws.currency", "USD");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SettingsProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route index element={<Home />} />
            <Route path="asset/:id" element={<AssetPage />} />
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
    expect(screen.queryByText(/tỷ giá USD\/VND/)).toBeNull();
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
    expect(screen.getByText(/tỷ giá USD\/VND/)).toBeInTheDocument();
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
