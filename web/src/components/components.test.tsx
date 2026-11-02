import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { sampleDetail, sampleList } from "../api/sample";
import { formatReturnPercent } from "../lib/format";
import { AssetCard } from "./AssetCard";
import { Disclaimer, DISCLAIMER_TEXT } from "./Disclaimer";
import { PriceRange } from "./PriceRange";
import { ProbabilityBadge } from "./ProbabilityBadge";
import { QuantileTable } from "./QuantileTable";
import { ReturnRange } from "./ReturnRange";
import { ModeToggle } from "./Toggles";

describe("ProbabilityBadge", () => {
  it("0,597 → 60% → 'Nghiêng tăng' kèm kỳ hạn và ▲", () => {
    render(<ProbabilityBadge probUp={0.597} horizonDays={7} />);
    expect(screen.getByText(/Nghiêng tăng/)).toBeInTheDocument();
    expect(screen.getByText("· 7 phiên")).toBeInTheDocument();
    expect(screen.getByText(/▲/)).toBeInTheDocument();
    expect(screen.getByText(/Xác suất giá tăng: 60%/)).toBeInTheDocument();
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "60");
  });

  it("0,404 → 40% → 'Nghiêng giảm' kèm ▼", () => {
    render(<ProbabilityBadge probUp={0.404} horizonDays={3} />);
    expect(screen.getByText(/Nghiêng giảm/)).toBeInTheDocument();
    expect(screen.getByText("· 3 phiên")).toBeInTheDocument();
    expect(screen.getByText(/▼/)).toBeInTheDocument();
  });

  it("0,55 → 'Chưa rõ xu hướng', không có ▲ hay ▼", () => {
    render(<ProbabilityBadge probUp={0.55} horizonDays={7} />);
    expect(screen.getByText(/Chưa rõ xu hướng/)).toBeInTheDocument();
    expect(screen.queryByText(/▲/)).toBeNull();
    expect(screen.queryByText(/▼/)).toBeNull();
    expect(screen.getByText(/Xác suất giá tăng: 55%/)).toBeInTheDocument();
  });

  it("biên kẹp 0,95 → '≥ 95%'; 0,945 → '95%'", () => {
    const { unmount } = render(<ProbabilityBadge probUp={0.95} horizonDays={7} />);
    expect(screen.getByText(/Xác suất giá tăng: ≥ 95%/)).toBeInTheDocument();
    unmount();
    render(<ProbabilityBadge probUp={0.945} horizonDays={7} />);
    expect(screen.getByText("Xác suất giá tăng: 95% (vạch giữa = 50%)")).toBeInTheDocument();
  });
});

describe("Disclaimer", () => {
  it("hằng dự phòng đúng chuỗi DISCLAIMER của API", () => {
    expect(DISCLAIMER_TEXT).toBe("Dự báo mang tính tham khảo, không phải lời khuyên đầu tư.");
    expect(DISCLAIMER_TEXT).toBe(sampleList().disclaimer);
  });

  it("ưu tiên chuỗi từ response API", () => {
    render(<Disclaimer text="Chuỗi từ API" />);
    expect(screen.getByText("Chuỗi từ API")).toBeInTheDocument();
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

describe("AssetCard", () => {
  const gold = sampleList().items.find((item) => item.asset === "gold")!;
  const renderCard = (hidePrice: boolean) =>
    render(
      <MemoryRouter>
        <AssetCard item={gold} hidePrice={hidePrice} />
      </MemoryRouter>,
    );

  it("hiện giá cuối và khoảng giá khi không ẩn giá", () => {
    renderCard(false);
    expect(screen.getByText(/Giá cuối ngày/)).toBeInTheDocument();
    expect(screen.getByText(/Khoảng giá 80% sau 7 ngày/)).toBeInTheDocument();
    expect(screen.getByText("USD/oz")).toBeInTheDocument();
  });

  it("ẩn giá, chỉ hiện % thay đổi và xác suất tăng khi hidePrice", () => {
    renderCard(true);
    expect(screen.queryByText(/Giá cuối ngày/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Khoảng giá 80%/)).not.toBeInTheDocument();
    expect(screen.queryByText("USD/oz")).not.toBeInTheDocument();
    expect(screen.getByText(/Thay đổi 80% sau 7 ngày/)).toBeInTheDocument();
    expect(screen.getByText(/Nghiêng tăng|Nghiêng giảm|Chưa rõ xu hướng/)).toBeInTheDocument();
    expect(screen.getByText("· 7 phiên")).toBeInTheDocument();
  });

  it("thẻ trang chủ dùng prob_up của h = 7", () => {
    render(
      <MemoryRouter>
        <AssetCard item={{ ...gold, h1: { ...gold.h1, prob_up: 0.3 }, h7: { ...gold.h7, prob_up: 0.62 } }} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Nghiêng tăng/)).toBeInTheDocument();
    expect(screen.getByText(/Xác suất giá tăng: 62%/)).toBeInTheDocument();
  });

  it("hiện nhãn 'Mốc thống kê 252 phiên' khi model_version là baseline-q252", () => {
    render(
      <MemoryRouter>
        <AssetCard item={{ ...gold, is_sample: false, model_version: "baseline-q252" }} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Mốc thống kê 252 phiên")).toBeInTheDocument();
    expect(screen.queryByText("Dữ liệu mẫu")).not.toBeInTheDocument();
  });

  it("không hiện nhãn mốc thống kê với mô hình khác hoặc dữ liệu mẫu", () => {
    render(
      <MemoryRouter>
        <AssetCard item={{ ...gold, is_sample: false, model_version: "dlinear-41e13dc5de3d" }} />
        <AssetCard item={gold} />
      </MemoryRouter>,
    );
    expect(screen.queryByText("Mốc thống kê 252 phiên")).not.toBeInTheDocument();
  });
});

describe("ReturnRange", () => {
  it("hiện khoảng log return theo %, không có giá", () => {
    render(<ReturnRange low={-0.0123} mid={0.001} high={0.0145} horizonDays={7} />);
    expect(
      screen.getByText(`${formatReturnPercent(-0.0123)} đến ${formatReturnPercent(0.0145)}`),
    ).toBeInTheDocument();
    expect(screen.getByText(/Sau 7 ngày/)).toBeInTheDocument();
    expect(screen.queryByText(/USD|VND/)).not.toBeInTheDocument();
  });
});

describe("QuantileTable", () => {
  const detail = sampleDetail("gold");

  it("mặc định có cột giá", () => {
    render(<QuantileTable asset="gold" detail={detail} currency="USD" />);
    expect(screen.getByText("Giá q10–q90")).toBeInTheDocument();
  });

  it("bỏ cột giá khi showPrices = false nhưng vẫn giữ phân vị return", () => {
    render(<QuantileTable asset="gold" detail={detail} currency="USD" showPrices={false} />);
    expect(screen.queryByText("Giá q10–q90")).not.toBeInTheDocument();
    expect(screen.getByText("q50")).toBeInTheDocument();
    expect(screen.getByText("Phân vị của log return")).toBeInTheDocument();
  });
});
