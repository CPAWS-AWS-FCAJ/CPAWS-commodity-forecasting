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
    expect(input()).toHaveValue("50.000.000");
  });

  it("gõ số: hiện dấu chấm phân cách nghìn ngay, kèm cách đọc", () => {
    render(<AmountConverter asset="wti" detail={sampleDetail("wti")} horizonDays={7} />);
    fireEvent.change(input(), { target: { value: "9000" } });
    expect(input()).toHaveValue("9.000");
    fireEvent.change(input(), { target: { value: "900000000" } });
    expect(input()).toHaveValue("900.000.000");
    expect(screen.getByText("= 900 triệu đồng")).toBeInTheDocument();
    expect(screen.getByText(/900\.000\.000 đồng có giá trị giả định/)).toBeInTheDocument();
    // gõ tiếp vào chuỗi đã có dấu chấm
    fireEvent.change(input(), { target: { value: "900.000.0001" } });
    expect(input()).toHaveValue("9.000.000.001");
  });

  it("chỉ nhận chữ số: chữ cái, dấu trừ bị bỏ qua và có lời nhắc", () => {
    render(<AmountConverter asset="wti" detail={sampleDetail("wti")} horizonDays={7} />);
    fireEvent.change(input(), { target: { value: "12000" } });
    fireEvent.change(input(), { target: { value: "12.000a" } });
    expect(input()).toHaveValue("12.000");
    expect(screen.getByText(/Chỉ nhận chữ số 0–9/)).toBeInTheDocument();
    fireEvent.change(input(), { target: { value: "-12.000" } });
    expect(input()).toHaveValue("12.000");
    // gõ hợp lệ thì lời nhắc trở về gợi ý thường
    fireEvent.change(input(), { target: { value: "12.0005" } });
    expect(input()).toHaveValue("120.005");
    expect(screen.queryByText(/Chỉ nhận chữ số 0–9/)).toBeNull();
  });

  it("giới hạn 12 chữ số; quá số tối đa thì báo lỗi", () => {
    render(<AmountConverter asset="wti" detail={sampleDetail("wti")} horizonDays={7} />);
    fireEvent.change(input(), { target: { value: "999999999999" } });
    expect(input()).toHaveValue("999.999.999.999");
    expect(screen.getByRole("alert")).toHaveTextContent("tối đa 100.000.000.000 đồng");
    expect(input()).toHaveAttribute("aria-invalid", "true");
    fireEvent.change(input(), { target: { value: "999.999.999.9999" } });
    expect(input()).toHaveValue("999.999.999.999");
    expect(screen.getByText("Tối đa 12 chữ số.")).toBeInTheDocument();
  });

  it("dưới mức tối thiểu: nhắc nhẹ (không phải alert), không hiện số tiền", () => {
    render(<AmountConverter asset="wti" detail={sampleDetail("wti")} horizonDays={7} />);
    fireEvent.change(input(), { target: { value: "5000" } });
    expect(input()).toHaveValue("5.000");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("tối thiểu 10.000 đồng");
    expect(input()).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByText(/Khoảng 80%:/)).toBeNull();
  });

  it.each(["900.000.000", "900000000", "900 000 000 đ"])("dán '%s' đều thành 900.000.000", (pasted) => {
    render(<AmountConverter asset="gold" detail={sampleDetail("gold")} horizonDays={7} />);
    fireEvent.paste(input(), { clipboardData: { getData: () => pasted } });
    expect(input()).toHaveValue("900.000.000");
    expect(screen.getByText(/900\.000\.000 đồng có giá trị giả định/)).toBeInTheDocument();
  });

  it("dán số thập phân hay chữ: giữ nguyên ô, báo lý do", () => {
    render(<AmountConverter asset="wti" detail={sampleDetail("wti")} horizonDays={7} />);
    fireEvent.paste(input(), { clipboardData: { getData: () => "1,5" } });
    expect(input()).toHaveValue("");
    expect(screen.getByText(/Chỉ nhận số nguyên đồng/)).toBeInTheDocument();
    fireEvent.paste(input(), { clipboardData: { getData: () => "10 triệu" } });
    expect(input()).toHaveValue("");
    expect(screen.getByText(/Chỉ nhận chữ số 0–9/)).toBeInTheDocument();
  });

  it("vàng: ghi chuỗi đại diện GLD; dầu không có dòng này", () => {
    const { unmount } = render(<AmountConverter asset="gold" detail={sampleDetail("gold")} horizonDays={7} />);
    expect(screen.getByText(/chuỗi đại diện GLD, không phải giá giao ngay/)).toBeInTheDocument();
    unmount();
    render(<AmountConverter asset="wti" detail={sampleDetail("wti")} horizonDays={7} />);
    expect(screen.queryByText(/chuỗi đại diện/)).toBeNull();
  });
});
