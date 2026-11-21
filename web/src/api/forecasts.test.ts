import { getForecastWithHistory } from "./forecasts";
import { sampleDetail } from "./sample";

// Gọi API thật (không dùng dữ liệu mẫu) qua apiGet giả lập.
vi.mock("./config", () => ({ config: { useSample: false, apiUrl: "https://api.example.test" } }));

const apiGet = vi.fn();
vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return { ...actual, apiGet: (...args: unknown[]) => apiGet(...args) };
});

describe("getForecastWithHistory", () => {
  beforeEach(() => apiGet.mockReset());

  it("gọi đúng tham số history và giữ nguyên price_history API trả về", async () => {
    const points = [{ base_date: "2026-11-20", last_price: 71.3 }];
    apiGet.mockResolvedValue({ ...sampleDetail("wti"), price_history: points });
    const detail = await getForecastWithHistory("wti", 520);
    expect(apiGet).toHaveBeenCalledWith("/forecasts/wti?history=520", undefined);
    expect(detail.price_history).toEqual(points);
  });

  it("API bản cũ không trả price_history: coi như mảng rỗng, không lỗi", async () => {
    apiGet.mockResolvedValue(sampleDetail("gold"));
    const detail = await getForecastWithHistory("gold");
    expect(detail.price_history).toEqual([]);
    expect(detail.asset).toBe("gold");
  });
});
