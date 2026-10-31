import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import collecting from "../../../tests/fixtures/accuracy/collecting.json";
import ready from "../../../tests/fixtures/accuracy/ready.json";
import type { AccuracyResponse } from "../api/types";
import { AccuracyFormatError, assertAccuracyStatuses } from "../lib/accuracy";
import { ReliabilityBlock } from "./ReliabilityBlock";

const flags = vi.hoisted(() => ({ useSample: true, sampleAccuracy: "collecting" }));
vi.mock("../api/config", () => ({
  config: {
    apiUrl: "https://api.example.test",
    get useSample() {
      return flags.useSample;
    },
    get sampleAccuracy() {
      return flags.sampleAccuracy;
    },
    historyAvailable: false,
    showMetalPrices: false,
    authEnabled: false,
    region: "ap-southeast-1",
    userPoolId: "",
    userPoolClientId: "",
  },
}));

function mount(showHorizons = true) {
  // retryDelay 0 để lỗi 503 (được thử lại 2 lần) không làm test chậm
  const client = new QueryClient({ defaultOptions: { queries: { retryDelay: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <ReliabilityBlock asset="gold" showHorizons={showHorizons} />
    </QueryClientProvider>,
  );
}

function pickFixture(which: "not_ready" | "collecting" | "ready") {
  flags.useSample = true;
  flags.sampleAccuracy = which;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ReliabilityBlock với fixtures Accuracy", () => {
  it("not_ready: 'Chưa có kết quả đánh giá', không số, không dòng 'Kể từ'", async () => {
    pickFixture("not_ready");
    mount();
    expect(await screen.findByText("Chưa có kết quả đánh giá")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).toBeNull();
    expect(screen.queryByText(/Kể từ/)).toBeNull();
  });

  it("collecting: 'Đang thu thập (4/20)', không hiện số overall", async () => {
    pickFixture("collecting");
    mount();
    expect(await screen.findByText(/Đang thu thập \(4\/20\)/)).toBeInTheDocument();
    expect(screen.queryByText(/cặp\)/)).toBeNull();
    // không có khối số overall (chỉ hiện khi ready)
    expect(screen.queryByText("Giá thực tế nằm trong khoảng 80%")).toBeNull();
    expect(screen.queryByText(/\d+% · \d+%/)).toBeNull();
    expect(screen.getByText("Kể từ 02/11/2026")).toBeInTheDocument();
  });

  it("collecting: theo h chỉ X/Y; n_obs = 0 hiện '—' kèm chú thích", async () => {
    pickFixture("collecting");
    mount();
    await screen.findByText(/Đang thu thập/);
    expect(screen.getByText("2/4")).toBeInTheDocument();
    expect(screen.getByText("1/3")).toBeInTheDocument();
    expect(screen.queryByText("0/0")).toBeNull();
    expect(screen.getAllByText("—")).toHaveLength(3);
    expect(screen.getByText(/chưa có cặp đã chấm/)).toBeInTheDocument();
  });

  it("ready: '73% (127/175 cặp)', độ rộng 1 chữ số, đúng chiều cạnh tỷ lệ tăng", async () => {
    pickFixture("ready");
    mount();
    expect(await screen.findByText("73% (127/175 cặp)")).toBeInTheDocument();
    expect(screen.getByText("1,8%")).toBeInTheDocument();
    expect(screen.getByText("56% · 70%")).toBeInTheDocument();
    expect(screen.getByText("Kể từ 02/11/2026")).toBeInTheDocument();
    // theo h vẫn chỉ số đếm
    expect(screen.getByText("16/28")).toBeInTheDocument();
  });

  it("ready nhưng metric undefined: không hiện số của metric đó", async () => {
    flags.useSample = false;
    const body = structuredClone(ready) as unknown as AccuracyResponse;
    body.overall.width_80_pct.display_status = "undefined";
    body.overall.width_80_pct.display_value = null;
    // value nội bộ vẫn còn nhưng không được dùng
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })));
    mount(false);
    expect(await screen.findByText("73% (127/175 cặp)")).toBeInTheDocument();
    expect(screen.queryByText(/1,8%/)).toBeNull();
  });

  it("503 accuracy_unavailable: 'Tạm thời chưa lấy được độ tin cậy'", async () => {
    flags.useSample = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ error: "accuracy_unavailable", message: "x" }), { status: 503 }),
      ),
    );
    mount();
    expect(await screen.findByText("Tạm thời chưa lấy được độ tin cậy")).toBeInTheDocument();
    expect(screen.queryByText("Không tải được dữ liệu")).toBeNull();
  });

  it("data_status lạ: báo lỗi, không đoán", async () => {
    flags.useSample = false;
    const body = { ...structuredClone(collecting), data_status: "almost_ready" };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })));
    mount();
    expect(await screen.findByText("Không tải được dữ liệu")).toBeInTheDocument();
    expect(screen.getByText(/data_status = almost_ready/)).toBeInTheDocument();
  });
});

describe("assertAccuracyStatuses", () => {
  it("chấp nhận cả 3 fixture", () => {
    expect(() => assertAccuracyStatuses(collecting as unknown as AccuracyResponse)).not.toThrow();
    expect(() => assertAccuracyStatuses(ready as unknown as AccuracyResponse)).not.toThrow();
  });

  it("display_status lạ ở overall hoặc by_horizon → AccuracyFormatError", () => {
    const overall = structuredClone(ready) as unknown as AccuracyResponse;
    overall.overall.coverage_80.display_status = "partial";
    expect(() => assertAccuracyStatuses(overall)).toThrow(AccuracyFormatError);

    const horizon = structuredClone(ready) as unknown as AccuracyResponse;
    horizon.by_horizon[2].sign_accuracy.display_status = "ready";
    expect(() => assertAccuracyStatuses(horizon)).toThrow(AccuracyFormatError);
  });
});
