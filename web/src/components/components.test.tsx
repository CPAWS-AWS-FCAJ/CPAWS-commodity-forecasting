import { fireEvent, render, screen } from "@testing-library/react";
import { PriceRange } from "./PriceRange";
import { ProbabilityBadge } from "./ProbabilityBadge";
import { ModeToggle } from "./Toggles";

describe("ProbabilityBadge", () => {
  it("hiện mũi tên, chữ và xác suất tăng", () => {
    render(<ProbabilityBadge probUp={0.56} horizonDays={7} />);
    expect(screen.getByText(/Khả năng tăng 56%/)).toBeInTheDocument();
    expect(screen.getByText(/▲/)).toBeInTheDocument();
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "56");
  });

  it("hiện 'giảm' kèm mũi tên xuống khi xác suất tăng dưới 50%", () => {
    render(<ProbabilityBadge probUp={0.4} horizonDays={3} />);
    expect(screen.getByText(/Khả năng giảm 60%/)).toBeInTheDocument();
    expect(screen.getByText(/▼/)).toBeInTheDocument();
  });

  it("ghi 'trên 90%' khi cả khoảng 80% dương", () => {
    render(<ProbabilityBadge probUp={0.95} zeroBelowQ10 horizonDays={7} />);
    expect(screen.getByText(/Khả năng tăng trên 90%/)).toBeInTheDocument();
  });
});

describe("PriceRange", () => {
  it("hiện khoảng USD và dòng phụ VND", () => {
    render(
      <PriceRange
        asset="wti"
        currency="USD"
        usdVnd={26000}
        low={70}
        mid={71}
        high={72}
        horizonDays={7}
      />,
    );
    expect(screen.getAllByText(/70,00–72,00 USD\/thùng/).length).toBeGreaterThan(0);
    expect(screen.getByText(/VND\/thùng/)).toBeInTheDocument();
  });

  it("cảnh báo giá vàng VND không phải vàng miếng trong nước", () => {
    render(
      <PriceRange
        asset="gold"
        currency="VND"
        usdVnd={26000}
        low={2000}
        mid={2010}
        high={2020}
        horizonDays={7}
      />,
    );
    expect(screen.getByText(/không phải giá vàng miếng trong nước/)).toBeInTheDocument();
  });
});

describe("ModeToggle", () => {
  it("báo trạng thái bằng aria-pressed và gọi onChange", () => {
    const onChange = vi.fn();
    render(<ModeToggle value="basic" onChange={onChange} />);
    expect(screen.getByRole("button", { name: "Cơ bản" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Nâng cao" }));
    expect(onChange).toHaveBeenCalledWith("advanced");
  });
});
