import { fireEvent, render, screen, within } from "@testing-library/react";
import { sampleCloses, sampleDetail } from "../api/sample";
import { FanChart } from "./FanChart";

const detail = sampleDetail("wti");

function group() {
  return screen.getByRole("group", { name: "Mốc xem lịch sử giá" });
}

describe("FanChart: mốc xem và phóng to", () => {
  it("lịch sử ngắn: mốc vượt dữ liệu bị tắt (không ẩn) và có lý do; mặc định mốc lớn nhất còn đủ", () => {
    render(<FanChart asset="wti" currency="USD" detail={detail} history={sampleCloses("wti").slice(-40)} />);
    const oneMonth = within(group()).getByRole("button", { name: "1 tháng" });
    expect(oneMonth).toHaveAttribute("aria-pressed", "true");
    for (const label of ["6 tháng", "1 năm", "2 năm"]) {
      const button = within(group()).getByRole("button", { name: label });
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(button).toHaveAttribute("title", expect.stringMatching(/cần \d+ giá cuối phiên, hiện mới có 40/));
      fireEvent.click(button);
      expect(button).toHaveAttribute("aria-pressed", "false");
    }
    expect(screen.getByText(/6 tháng, 1 năm, 2 năm: chưa đủ dữ liệu/)).toBeInTheDocument();
    expect(oneMonth).toHaveAttribute("aria-pressed", "true");
  });

  it("chưa mốc nào đủ dữ liệu: hiện toàn bộ số phiên đang có", () => {
    render(<FanChart asset="wti" currency="USD" detail={detail} history={sampleCloses("wti").slice(-12)} />);
    expect(screen.getByText("Đang hiện toàn bộ 12 phiên giá cuối hiện có.")).toBeInTheDocument();
    expect(within(group()).getAllByRole("button").every((b) => b.getAttribute("aria-disabled") === "true")).toBe(true);
  });

  it("lỗi lịch sử: vẫn vẽ phần dự báo, có dòng báo", () => {
    render(<FanChart asset="wti" currency="USD" detail={detail} history={undefined} historyFailed />);
    expect(screen.getByRole("status")).toHaveTextContent("Chưa tải được lịch sử giá");
    expect(screen.queryByRole("group", { name: "Mốc xem lịch sử giá" })).toBeNull();
    expect(screen.getByText(/Trung vị dự báo từng phiên/)).toBeInTheDocument();
  });

  it("Phóng to / Thu nhỏ / Đặt lại bằng nút (dùng được bằng bàn phím); Đặt lại về cả mốc", () => {
    render(<FanChart asset="wti" currency="USD" detail={detail} history={sampleCloses("wti")} />);
    const zoomIn = screen.getByRole("button", { name: "Phóng to" });
    const zoomOut = screen.getByRole("button", { name: "Thu nhỏ" });
    const reset = screen.getByRole("button", { name: "Đặt lại" });
    expect(reset).toBeDisabled();
    expect(zoomOut).toBeDisabled();
    fireEvent.click(zoomIn);
    fireEvent.click(zoomIn);
    expect(reset).toBeEnabled();
    expect(zoomOut).toBeEnabled();
    // phóng to giữ mép phải nên phần dự báo vẫn trong khung
    expect(screen.queryByText(/dự báo đang nằm ngoài đoạn đang xem/)).toBeNull();
    fireEvent.click(reset);
    expect(reset).toBeDisabled();
  });

  it("đủ 2 năm dữ liệu: mặc định vẫn xem 1 tháng để 7 phiên dự báo đủ rộng", () => {
    render(<FanChart asset="wti" currency="USD" detail={detail} history={sampleCloses("wti")} />);
    expect(within(group()).getByRole("button", { name: "1 tháng" })).toHaveAttribute("aria-pressed", "true");
    expect(within(group()).getByRole("button", { name: "2 năm" })).not.toHaveAttribute("aria-disabled", "true");
  });

  it("đổi mốc thì khung về cả mốc", () => {
    render(<FanChart asset="wti" currency="USD" detail={detail} history={sampleCloses("wti")} />);
    fireEvent.click(screen.getByRole("button", { name: "Phóng to" }));
    expect(screen.getByRole("button", { name: "Đặt lại" })).toBeEnabled();
    fireEvent.click(within(group()).getByRole("button", { name: "1 năm" }));
    expect(within(group()).getByRole("button", { name: "1 năm" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Đặt lại" })).toBeDisabled();
  });

  it("chú thích nói rõ chấm đỏ là trung vị, không phải giảm; ghi chú trục không bắt đầu từ 0", () => {
    render(<FanChart asset="gold" currency="VND" detail={sampleDetail("gold")} history={sampleCloses("gold")} />);
    expect(screen.getByRole("heading", { name: /Giá thực tế và dự báo/ })).toHaveTextContent("VND/lượng");
    expect(screen.getByText(/chấm đỏ là mức giữa, không có nghĩa là giảm/)).toBeInTheDocument();
    expect(screen.getByText("Trục dọc: VND/lượng, không bắt đầu từ 0.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Tìm hiểu thêm/ })).toHaveAttribute("href", "/guide#doc-bieu-do");
  });

  it("hướng dẫn phóng to: chuột/bàn phím nói phím ← →; màn cảm ứng không nói phím", () => {
    const history = sampleCloses("wti").slice(-60);
    const { unmount } = render(<FanChart asset="wti" currency="USD" detail={detail} history={history} />);
    expect(screen.getByText(/Bàn phím: Tab tới một đầu thanh/)).toBeInTheDocument();
    unmount();

    vi.stubGlobal(
      "matchMedia",
      (query: string) =>
        ({
          matches: query === "(pointer: coarse)",
          addEventListener: () => {},
          removeEventListener: () => {},
        }) as unknown as MediaQueryList,
    );
    try {
      render(<FanChart asset="wti" currency="USD" detail={detail} history={history} />);
      expect(
        screen.getByText("Phóng to: kéo hai đầu thanh dưới biểu đồ, hoặc dùng các nút Phóng to, Thu nhỏ, Đặt lại."),
      ).toBeInTheDocument();
      expect(screen.queryByText(/Bàn phím/)).toBeNull();
      expect(screen.getByRole("button", { name: "Phóng to" })).toHaveClass("pointer-coarse:min-h-11");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
