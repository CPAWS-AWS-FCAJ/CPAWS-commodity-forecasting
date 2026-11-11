import { fireEvent, render, screen } from "@testing-library/react";
import { sampleDetail } from "../api/sample";
import { AMOUNT_NOTE, amountRange } from "../lib/amount";
import { formatNumber } from "../lib/format";
import { AmountConverter } from "./AmountConverter";

function input() {
  return screen.getByLabelText("Số tiền (đồng)");
}

describe("AmountConverter (ADR-0005 mục (2))", () => {
  it("chưa nhập: không có số tiền giả định, vẫn có đủ lưu ý", () => {
    render(<AmountConverter asset="wti" detail={sampleDetail("wti")} horizonDays={7} />);
    expect(screen.getByText("Nhập số tiền để xem giá trị giả định sau 7 phiên.")).toBeInTheDocument();
    expect(screen.queryByText(/Khoảng 80%:/)).toBeNull();
    expect(screen.getByText(AMOUNT_NOTE)).toBeInTheDocument();
    expect(screen.getByText("Giả định tỷ giá USD/VND không đổi trong 7 phiên.")).toBeInTheDocument();
    expect(screen.getByText(/không phải lợi nhuận thực nhận hay được bảo đảm/)).toBeInTheDocument();
    expect(input()).toHaveAttribute("inputmode", "numeric");
  });

  it("nhập 10.000.000: khoảng tính từ returns q10/q90 của h đang chọn", () => {
    const detail = sampleDetail("wti");
    render(<AmountConverter asset="wti" detail={detail} horizonDays={3} />);
    fireEvent.change(input(), { target: { value: "10.000.000" } });
    const h3 = detail.horizons.find((item) => item.h === 3)!;
    const expected = amountRange(10_000_000, h3.returns[1], h3.returns[3], h3.returns[5]);
    expect(
      screen.getByText(`${formatNumber(expected.low)} – ${formatNumber(expected.high)} đồng`),
    ).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`^${formatNumber(expected.mid)} đồng`))).toBeInTheDocument();
    expect(screen.getByText(/sau 3 phiên \(phiên/)).toBeInTheDocument();
  });

  it("đổi h thì kết quả đổi theo", () => {
    const detail = sampleDetail("brent");
    const { rerender } = render(<AmountConverter asset="brent" detail={detail} horizonDays={1} />);
    fireEvent.change(input(), { target: { value: "50000000" } });
    expect(screen.getByText(/sau 1 phiên/)).toBeInTheDocument();
    rerender(<AmountConverter asset="brent" detail={detail} horizonDays={7} />);
    expect(screen.getByText(/sau 7 phiên/)).toBeInTheDocument();
    expect(input()).toHaveValue("50000000");
  });

  it("nhập sai: báo lỗi, không hiện số tiền", () => {
    render(<AmountConverter asset="wti" detail={sampleDetail("wti")} horizonDays={7} />);
    fireEvent.change(input(), { target: { value: "1.5" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Chỉ nhập số nguyên đồng");
    expect(input()).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText(/Khoảng 80%:/)).toBeNull();
    fireEvent.change(input(), { target: { value: "5.000" } });
    expect(screen.getByRole("alert")).toHaveTextContent("tối thiểu 10.000 đồng");
  });

  it("vàng: ghi chuỗi đại diện GLD; dầu không có dòng này", () => {
    const { unmount } = render(<AmountConverter asset="gold" detail={sampleDetail("gold")} horizonDays={7} />);
    expect(screen.getByText(/chuỗi đại diện GLD, không phải giá giao ngay/)).toBeInTheDocument();
    unmount();
    render(<AmountConverter asset="wti" detail={sampleDetail("wti")} horizonDays={7} />);
    expect(screen.queryByText(/chuỗi đại diện/)).toBeNull();
  });
});
