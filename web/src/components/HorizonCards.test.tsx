import { fireEvent, render, screen, within } from "@testing-library/react";
import { sampleDetail } from "../api/sample";
import type { ForecastDetail } from "../api/types";
import { HorizonCards } from "./HorizonCards";

/** Bản ghi mẫu với prob_up đặt sẵn theo h để kiểm nhãn 60/40 trên số đã làm tròn. */
function withProbs(detail: ForecastDetail, probs: number[]): ForecastDetail {
  return { ...detail, horizons: detail.horizons.map((h, i) => ({ ...h, prob_up: probs[i] })) };
}

function cards() {
  return screen.getAllByRole("button", { name: /^Sau \d phiên:/ });
}

describe("HorizonCards", () => {
  it("7 thẻ theo thứ tự h, nhãn 60/40 kèm '· h phiên' và xác suất từ prob_up", () => {
    const detail = withProbs(sampleDetail("wti"), [0.597, 0.404, 0.55, 0.95, 0.05, 0.945, 0.5]);
    // Đảo thứ tự horizons: thẻ vẫn phải xếp h = 1…7
    render(
      <HorizonCards
        asset="wti"
        detail={{ ...detail, horizons: [...detail.horizons].reverse() }}
        currency="USD"
        hidePrice={false}
        selected={7}
        onSelect={() => {}}
      />,
    );
    const all = cards();
    expect(all).toHaveLength(7);
    const text = all.map((card) => card.textContent ?? "");
    expect(text[0]).toContain("Nghiêng tăng · 1 phiên");
    expect(text[0]).toContain("Xác suất tăng 60%");
    expect(text[1]).toContain("Nghiêng giảm · 2 phiên");
    expect(text[2]).toContain("Chưa rõ xu hướng · 3 phiên");
    expect(text[3]).toContain("≥ 95%");
    expect(text[4]).toContain("≤ 5%");
    expect(text[5]).toContain("Xác suất tăng 95%");
    expect(text[6]).toContain("Chưa rõ xu hướng · 7 phiên");
    expect(all[6]).toHaveAttribute("aria-pressed", "true");
  });

  it("dầu: khoảng 80% có giá theo đơn vị đang chọn và % thay đổi; mức giữa q50", () => {
    const detail = sampleDetail("wti");
    const h7 = detail.horizons.find((h) => h.h === 7)!;
    render(<HorizonCards asset="wti" detail={detail} currency="VND" hidePrice={false} selected={7} onSelect={() => {}} />);
    const card = cards()[6];
    expect(card.textContent).toContain("VND/thùng");
    expect(card.textContent).toMatch(/[+−]?\d+,\d% đến [+−]?\d+,\d%/);
    expect(within(card).getByText(/Mức giữa:/).textContent).toContain("VND/thùng");
    expect(card.textContent).toContain(h7.target_date.split("-").reverse().join("/"));
  });

  it("vàng ẩn giá: chỉ %, không USD/VND", () => {
    render(<HorizonCards asset="gold" detail={sampleDetail("gold")} currency="USD" hidePrice selected={7} onSelect={() => {}} />);
    for (const card of cards()) {
      expect(card.textContent).not.toMatch(/USD|VND/);
      expect(card.textContent).toMatch(/Khoảng 80%[+−]?\d+,\d% đến [+−]?\d+,\d%/);
    }
  });

  it("bấm thẻ gọi onSelect với h của thẻ", () => {
    const onSelect = vi.fn();
    render(<HorizonCards asset="brent" detail={sampleDetail("brent")} currency="USD" hidePrice={false} selected={7} onSelect={onSelect} />);
    fireEvent.click(cards()[2]);
    expect(onSelect).toHaveBeenCalledWith(3);
  });
});
