import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ChatResponse } from "../api/types";
import { ChatPanel } from "./ChatPanel";

const flags = vi.hoisted(() => ({ useSample: false }));
vi.mock("../api/config", () => ({
  config: {
    apiUrl: "https://api.example.test",
    get useSample() {
      return flags.useSample;
    },
    sampleAccuracy: "collecting",
    accuracyApiEnabled: false,
    historyAvailable: false,
    showMetalPrices: false,
    authEnabled: false,
    region: "ap-southeast-1",
    userPoolId: "",
    userPoolClientId: "",
  },
}));

const DISCLAIMER = "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư.";

function reply(overrides: Partial<ChatResponse> = {}): ChatResponse {
  return {
    request_id: "req-1",
    answer: `WTI phiên tới: xác suất tăng 51%.\n- Khoảng 80%: −1,8% đến +1,9%.\n\n${DISCLAIMER}`,
    branch: "complex",
    prompt_version: "chatbot-haiku-v2",
    forecasts_used: [
      { asset: "wti", base_date: "2026-10-30", model_version: "baseline-q252", is_sample: false, stale: false },
    ],
    citations: [],
    truncated: false,
    blocked: false,
    quota: { limit: 20, used: 3, remaining: 17, reset_at: "2026-11-03T17:00:00Z" },
    disclaimer: DISCLAIMER,
    ...overrides,
  };
}

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  flags.useSample = false;
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function ask(text: string) {
  const box = screen.getByLabelText("Câu hỏi cho chatbot");
  fireEvent.change(box, { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Gửi" }));
}

function sentBody(call = 0) {
  const [url, init] = fetchMock.mock.calls[call] as [string, RequestInit];
  expect(url).toBe("https://api.example.test/chat");
  expect(init.method).toBe("POST");
  return JSON.parse(init.body as string);
}

describe("ChatPanel", () => {
  it("gửi câu hỏi kèm ngữ cảnh tài sản, hiện câu trả lời dạng văn bản và số lượt còn lại", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, reply()));
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    ask("  Phiên tới có tăng không?  ");

    expect(await screen.findByText(/xác suất tăng 51%/)).toBeInTheDocument();
    expect(sentBody()).toEqual({
      question: "Phiên tới có tăng không?",
      context: { asset: "wti", page: "product" },
    });
    expect(screen.getByText("Phiên tới có tăng không?")).toBeInTheDocument();
    expect(screen.getByText("Còn 17/20 lượt hôm nay")).toBeInTheDocument();
    // answer đã có disclaimer thì không lặp lại dòng disclaimer riêng
    expect(screen.getAllByText(new RegExp(DISCLAIMER))).toHaveLength(1);
  });

  it("câu thứ hai gửi kèm lịch sử lượt trước (user rồi assistant)", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, reply({ answer: "Trả lời một." })))
      .mockResolvedValueOnce(jsonResponse(200, reply({ answer: "Trả lời hai." })));
    render(<ChatPanel asset="gold" assetName="Vàng" />);
    ask("Câu một?");
    await screen.findByText("Trả lời một.");
    ask("Câu hai?");
    await screen.findByText("Trả lời hai.");
    expect(sentBody(1).history).toEqual([
      { role: "user", text: "Câu một?" },
      { role: "assistant", text: "Trả lời một." },
    ]);
  });

  it("HTML trong answer hiện như chữ; link chỉ lấy từ citations http/https, mở tab mới an toàn", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        200,
        reply({
          answer: "<img src=x onerror=alert(1)> xem https://evil.example/x",
          citations: [
            {
              title: "FOMC statement",
              source: "Federal Reserve",
              published_at: "2026-10-28T18:00:00Z",
              link: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm",
            },
            { title: "Tin lạ", source: "X", published_at: "2026-10-27T00:00:00Z", link: "javascript:alert(1)" },
          ],
        }),
      ),
    );
    const { container } = render(<ChatPanel asset="gold" assetName="Vàng" />);
    ask("Có tin gì?");

    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1); // URL trong answer không thành link, citation javascript: bị bỏ link
    expect(links[0]).toHaveAttribute("href", expect.stringMatching(/^https:\/\/www\.federalreserve\.gov\//));
    expect(links[0]).toHaveAttribute("target", "_blank");
    expect(links[0]).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("Tin lạ")).toBeInTheDocument();
    expect(screen.getByText(/Federal Reserve · 28\/10\/2026/)).toBeInTheDocument();
    // answer thiếu disclaimer → web tự hiện dòng disclaimer
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument();
  });

  it("dữ liệu mẫu, dữ liệu cũ và câu bị cắt có nhãn riêng", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        200,
        reply({
          truncated: true,
          forecasts_used: [
            { asset: "wti", base_date: "2026-10-14", model_version: "sample", is_sample: true, stale: true },
          ],
        }),
      ),
    );
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    ask("Dự báo?");
    expect(await screen.findByText("Dữ liệu mẫu")).toBeInTheDocument();
    expect(screen.getByText("Dữ liệu chưa mới")).toBeInTheDocument();
    expect(screen.getByText(/Câu trả lời bị cắt/)).toBeInTheDocument();
  });

  it("429 hết lượt trong ngày: hiện message của server kèm giờ làm mới", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(429, {
        error: "rate_limited",
        message: "Bạn đã dùng hết 20 lượt hỏi hôm nay.",
        reset_at: "2026-11-03T17:00:00Z",
      }),
    );
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    ask("Hỏi thêm?");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Bạn đã dùng hết 20 lượt hỏi hôm nay\..*00:00.*giờ Việt Nam/);
  });

  it("429 do throttling của API Gateway: câu chung; lượt lỗi không vào lịch sử", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(429, { message: "Too Many Requests" }))
      .mockResolvedValueOnce(jsonResponse(200, reply({ answer: "OK." })));
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    ask("Câu một?");
    expect(await screen.findByRole("alert")).toHaveTextContent("Bạn đã hỏi quá nhiều, thử lại sau.");
    ask("Câu hai?");
    await screen.findByText("OK.");
    expect(sentBody(1).history).toBeUndefined();
  });

  it("Enter gửi, Shift+Enter không gửi; câu quá 500 ký tự bị chặn trước khi gọi API", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, reply({ answer: "Đã nhận." })));
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    const box = screen.getByLabelText("Câu hỏi cho chatbot");

    fireEvent.change(box, { target: { value: "a".repeat(501) } });
    expect(screen.getByRole("button", { name: "Gửi" })).toBeDisabled();
    expect(screen.getByText(/dài quá 500/)).toBeInTheDocument();

    fireEvent.change(box, { target: { value: "Xin chào" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: "Enter" });
    await screen.findByText("Đã nhận.");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("chế độ dữ liệu mẫu: chatbot tắt, không gọi API", () => {
    flags.useSample = true;
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    expect(screen.getByLabelText("Câu hỏi cho chatbot")).toBeDisabled();
    expect(screen.getByText(/chatbot tạm tắt/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("Xóa hội thoại: làm trống danh sách", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, reply({ answer: "Một." })));
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    ask("Hỏi?");
    await screen.findByText("Một.");
    fireEvent.click(screen.getByRole("button", { name: "Xóa hội thoại" }));
    await waitFor(() => expect(screen.queryByText("Một.")).toBeNull());
  });
});
