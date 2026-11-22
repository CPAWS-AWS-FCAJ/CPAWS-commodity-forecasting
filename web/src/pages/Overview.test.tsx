import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Overview from "./Overview";
import { METAL_PRICE_NOTE } from "../lib/source";
import { SettingsProvider } from "../lib/settings";
import { SOURCE_ATTRIBUTION } from "../lib/source";

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

function mount(currency: "USD" | "VND" = "USD") {
  window.localStorage.setItem("cpaws.currency", currency);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SettingsProvider>
        <MemoryRouter initialEntries={["/overview"]}>
          <Routes>
            <Route path="overview" element={<Overview />} />
          </Routes>
        </MemoryRouter>
      </SettingsProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => cleanup());

describe("trang Tổng quan giá", () => {
  it("hiện 4 ô giá, thay đổi so với phiên trước có mũi tên và chữ, nguồn và ghi chú GLD/SLV", async () => {
    flags.show = true;
    mount();
    expect(await screen.findByRole("heading", { name: "Tổng quan giá" })).toBeInTheDocument();
    for (const name of ["Vàng", "Bạc", "Dầu Brent", "Dầu WTI"]) {
      expect(await screen.findByRole("button", { name: new RegExp(`^${name}`) })).toBeInTheDocument();
    }
    expect((await screen.findAllByText(/so với phiên/)).length).toBe(4);
    expect(screen.getAllByText(/^(tăng|giảm|không đổi)$/).length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText(SOURCE_ATTRIBUTION)).toBeInTheDocument();
    expect(screen.getByText(METAL_PRICE_NOTE)).toBeInTheDocument();
    expect(screen.getAllByText("Dữ liệu mẫu").length).toBeGreaterThan(0);
  });

  it("chọn sản phẩm khác đổi khối biểu đồ, có link sang trang dự báo", async () => {
    flags.show = true;
    mount();
    fireEvent.click(await screen.findByRole("button", { name: /^Dầu WTI/ }));
    const panel = await screen.findByRole("region", { name: "Dầu WTI" });
    expect(within(panel).getByText(/Giá cuối phiên, USD\/thùng/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Xem dự báo chi tiết" })).toHaveAttribute("href", "/asset/wti");
  });

  it("mốc 7 phiên, 1 tháng, 6 tháng, 1 năm, 2 năm; mặc định 1 tháng; đổi mốc được", async () => {
    flags.show = true;
    mount();
    await screen.findByRole("region", { name: "Vàng" });
    const group = screen.getByRole("group", { name: "Khoảng thời gian" });
    expect(within(group).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "7 phiên",
      "1 tháng",
      "6 tháng",
      "1 năm",
      "2 năm",
    ]);
    expect(within(group).getByRole("button", { name: "1 tháng" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(group).getByRole("button", { name: "7 phiên" }));
    expect(within(group).getByRole("button", { name: "7 phiên" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(group).getByRole("button", { name: "2 năm" }));
    expect(within(group).getByRole("button", { name: "2 năm" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Dữ liệu từ .*, 520 phiên/)).toBeInTheDocument();
  });

  it("ô đang chọn viền màu nhận diện của sản phẩm", async () => {
    flags.show = true;
    mount();
    const gold = await screen.findByRole("button", { name: /^Vàng/ });
    expect(gold).toHaveAttribute("aria-pressed", "true");
    expect(gold.className).toContain("border-gold");
    fireEvent.click(screen.getByRole("button", { name: /^Dầu WTI/ }));
    expect(screen.getByRole("button", { name: /^Dầu WTI/ }).className).toContain("border-wti");
    expect(screen.getByRole("button", { name: /^Vàng/ }).className).not.toContain("border-gold");
  });

  it("cờ tắt: không hiện giá vàng, bạc, mặc định chọn dầu Brent", async () => {
    flags.show = false;
    mount();
    expect((await screen.findAllByText(/Giá đang được ẩn/)).length).toBe(2);
    expect(await screen.findByRole("region", { name: "Dầu Brent" })).toBeInTheDocument();
    expect(screen.queryByText(METAL_PRICE_NOTE)).toBeNull();
    expect(screen.queryByText(/USD\/oz/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Vàng/ }));
    expect(await screen.findByText(/Giá vàng đang được ẩn/)).toBeInTheDocument();
  });

  it("VND: có dòng tỷ giá áp dụng cho mọi phiên và ghi chú vàng quy đổi", async () => {
    flags.show = true;
    mount("VND");
    expect(await screen.findByText(/Quy đổi VND theo tỷ giá USD\/VND/)).toBeInTheDocument();
    expect(screen.getByText(/không phải giá vàng miếng trong nước/)).toBeInTheDocument();
  });

  it("không có nút tải xuống, xuất dữ liệu hay mua bán", async () => {
    flags.show = true;
    mount();
    await screen.findByRole("region", { name: "Vàng" });
    for (const text of [/tải/i, /xuất/i, /download/i, /export/i, /csv/i, /^mua/i, /^bán/i]) {
      expect(screen.queryByRole("button", { name: text })).toBeNull();
      expect(screen.queryByRole("link", { name: text })).toBeNull();
    }
  });
});
