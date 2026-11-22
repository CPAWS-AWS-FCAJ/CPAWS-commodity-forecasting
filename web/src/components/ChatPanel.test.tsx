import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import type { ChatResponse } from "../api/types";
import { AuthContext, SAMPLE_AUTH, type AuthState } from "../auth/AuthContext";
import { CHAT_STORAGE_PREFIX, chatStorageKey } from "../lib/chatHistory";
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
  window.sessionStorage.clear();
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
    expect(screen.getByText("Mã tra cứu: req-1")).toBeInTheDocument();
    expect(screen.getByText(/làm mới lúc 00:00 ngày 04\/11/)).toBeInTheDocument();
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

  it("bỏ cặp ** khi hiển thị; history và kiểm disclaimer vẫn dùng answer gốc", async () => {
    const first = `Xác suất tăng **51%**, 2 * 3 giữ nguyên.\n** lẻ giữ nguyên\n**<b>x</b>**\n\n**${DISCLAIMER}**`;
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, reply({ answer: first })))
      .mockResolvedValueOnce(jsonResponse(200, reply({ answer: "Hai." })));
    const { container } = render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    ask("Câu một?");

    const bubble = await screen.findByText(/Xác suất tăng 51%, 2 \* 3 giữ nguyên\./);
    expect(bubble.textContent).toContain("\n** lẻ giữ nguyên\n<b>x</b>\n");
    expect(bubble.textContent).not.toContain("**51%");
    expect(container.querySelector("b")).toBeNull();
    // answer gốc vẫn chứa nguyên disclaimer (bọc **) → không lặp dòng riêng; hiển thị không còn **
    expect(screen.queryByText(DISCLAIMER)).toBeNull();
    expect(bubble.textContent?.endsWith(`\n\n${DISCLAIMER}`)).toBe(true);

    ask("Câu hai?");
    await screen.findByText("Hai.");
    expect(sentBody(1).history[1]).toEqual({ role: "assistant", text: first });
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
    // 18:00 UTC ngày 28/10 = 01:00 ngày 29/10 giờ Việt Nam
    expect(screen.getByText(/Federal Reserve · 29\/10\/2026/)).toBeInTheDocument();
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

  it("sau 429 rate_limited không còn hiện số lượt cũ", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, reply())).mockResolvedValueOnce(
      jsonResponse(429, {
        error: "rate_limited",
        message: "Bạn đã dùng hết 20 lượt hỏi hôm nay.",
        reset_at: "2026-11-03T17:00:00Z",
      }),
    );
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    ask("Câu một?");
    await screen.findByText("Còn 17/20 lượt hôm nay");
    ask("Câu hai?");
    await screen.findByRole("alert");
    expect(screen.getByText("Đã hết lượt hỏi hôm nay")).toBeInTheDocument();
    expect(screen.queryByText(/Còn 17\/20/)).toBeNull();
  });

  it("reset_at sai dạng không làm hỏng trang", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, reply({ quota: { limit: 20, used: 1, remaining: 19, reset_at: "không phải ngày" } })),
    );
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    ask("Câu một?");
    expect(await screen.findByText("Còn 19/20 lượt hôm nay")).toBeInTheDocument();
    expect(screen.queryByText(/làm mới lúc/)).toBeNull();
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

  it("Xóa cuộc trò chuyện: hỏi xác nhận tại chỗ; Hủy giữ nguyên, Xóa làm trống và xóa bản lưu", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, reply({ answer: "Một." })));
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    expect(screen.queryByRole("button", { name: "Xóa cuộc trò chuyện" })).toBeNull();
    ask("Hỏi?");
    await screen.findByText("Một.");
    expect(window.sessionStorage.getItem(chatStorageKey("sample", "wti"))).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Xóa cuộc trò chuyện" }));
    const cancel = screen.getByRole("button", { name: "Hủy" });
    expect(cancel).toHaveFocus();
    expect(screen.getByText("Xóa toàn bộ cuộc trò chuyện?")).toBeInTheDocument();
    fireEvent.click(cancel);
    expect(screen.getByText("Một.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Xóa cuộc trò chuyện" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Xóa cuộc trò chuyện" }));
    fireEvent.click(screen.getByRole("button", { name: "Xóa" }));
    await waitFor(() => expect(screen.queryByText("Một.")).toBeNull());
    expect(window.sessionStorage.getItem(chatStorageKey("sample", "wti"))).toBeNull();
    expect(screen.getByLabelText("Câu hỏi cho chatbot")).toHaveFocus();
  });

  it("Esc trong bước xác nhận chỉ hủy xác nhận, không đóng ngăn chatbot", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, reply({ answer: "Một." })));
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    fireEvent.click(screen.getByRole("button", { name: "Hỏi chatbot" }));
    const dialog = screen.getByRole("dialog", { name: "Chatbot Dầu WTI" });
    fireEvent.change(within(dialog).getByLabelText("Câu hỏi cho chatbot"), { target: { value: "Hỏi?" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Gửi" }));
    await within(dialog).findByText("Một.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Xóa cuộc trò chuyện" }));
    fireEvent.keyDown(within(dialog).getByRole("button", { name: "Hủy" }), { key: "Escape" });
    expect(screen.getByRole("dialog", { name: "Chatbot Dầu WTI" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Xóa cuộc trò chuyện" })).toBeInTheDocument();
  });

  it("điện thoại: ngăn chatbot là hộp thoại — focus vào nút Đóng, khóa cuộn nền, Esc đóng và trả focus", () => {
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    const openButton = screen.getByRole("button", { name: "Hỏi chatbot" });
    fireEvent.click(openButton);
    const dialog = screen.getByRole("dialog", { name: "Chatbot Dầu WTI" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    // Sheet cao theo dvh (không theo vh), chừa vùng an toàn
    expect(dialog.className).toMatch(/h-\[85dvh\]/);
    expect(dialog.className).toMatch(/safe-area-inset-bottom/);
    const close = within(dialog).getByRole("button", { name: "Đóng" });
    expect(close).toHaveFocus();
    expect(close).toHaveClass("min-h-11");
    expect(document.body.style.overflow).toBe("hidden");

    // Tab ở phần tử cuối quay về phần tử đầu (giữ focus trong ngăn)
    const focusables = dialog.querySelectorAll<HTMLElement>("button:not([disabled]), textarea:not([disabled])");
    focusables[focusables.length - 1].focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(focusables[0]).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Chatbot Dầu WTI" })).toBeNull();
    expect(openButton).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
  });

  it("bấm nền hoặc nút Đóng thì đóng ngăn; ô nhập 16 px dưới lg (Safari iOS không tự phóng to)", () => {
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    fireEvent.click(screen.getByRole("button", { name: "Hỏi chatbot" }));
    fireEvent.click(screen.getByTestId("chat-backdrop"));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Hỏi chatbot" }));
    const dialog = screen.getByRole("dialog", { name: "Chatbot Dầu WTI" });
    const box = within(dialog).getByLabelText("Câu hỏi cho chatbot");
    expect(box).toHaveClass("text-base");
    expect(box).not.toHaveClass("text-sm");
    fireEvent.click(within(dialog).getByRole("button", { name: "Đóng" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("máy tính: Phóng to mở khung lớn, giữ câu đang gõ và hội thoại; Thu nhỏ/Esc trả focus về nút", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, reply()));
    render(<ChatPanel asset="wti" assetName="Dầu WTI" />);
    ask("Phiên tới có tăng không?");
    expect(await screen.findByText(/xác suất tăng 51%/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Câu hỏi cho chatbot"), { target: { value: "Còn 7 phiên?" } });

    const expand = screen.getByRole("button", { name: "Phóng to khung chat" });
    expect(expand).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(expand);
    expect(expand).toHaveAttribute("aria-expanded", "true");
    const dialog = screen.getByRole("dialog", { name: "Chatbot Dầu WTI, khung lớn" });
    // Chỉ một ô nhập (cột bên cạnh nhường chỗ cho khung lớn), chữ đang gõ còn nguyên
    expect(screen.getAllByLabelText("Câu hỏi cho chatbot")).toHaveLength(1);
    expect(within(dialog).getByLabelText("Câu hỏi cho chatbot")).toHaveValue("Còn 7 phiên?");
    expect(within(dialog).getByText(/xác suất tăng 51%/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Thu nhỏ" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.click(within(dialog).getByRole("button", { name: "Thu nhỏ" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(expand).toHaveFocus();
    expect(screen.getByLabelText("Câu hỏi cho chatbot")).toHaveValue("Còn 7 phiên?");

    fireEvent.click(expand);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.body.style.overflow).toBe("");
  });
});

describe("ChatPanel: lịch sử trong phiên (sessionStorage)", () => {
  function signedIn(userId: string): AuthState {
    return {
      status: "authenticated",
      sampleMode: false,
      account: { username: userId, userId, name: "Lan" },
      signOut: async () => {},
    };
  }

  function renderAs(auth: AuthState, asset: "wti" | "gold" = "wti") {
    const wrap = ({ children }: { children: ReactNode }) => (
      <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>
    );
    return render(<ChatPanel asset={asset} assetName={asset === "wti" ? "Dầu WTI" : "Vàng"} />, { wrapper: wrap });
  }

  it("lưu câu hỏi, câu trả lời, nguồn, mã tra cứu; mở lại (chuyển trang/tải lại) thì khôi phục", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        200,
        reply({
          request_id: "req-luu",
          citations: [{ title: "EIA tuần này", source: "EIA", published_at: "2026-11-02T10:00:00Z", link: "https://www.eia.gov/x" }],
        }),
      ),
    );
    renderAs(signedIn("sub-a"));
    expect(screen.getByText("Cuộc trò chuyện được giữ đến khi bạn đóng trang.")).toBeInTheDocument();
    ask("Phiên tới có tăng không?");
    await screen.findByText(/xác suất tăng 51%/);

    const raw = window.sessionStorage.getItem(chatStorageKey("sub-a", "wti"));
    expect(raw).not.toBeNull();
    const stored = JSON.parse(raw!);
    expect(stored.v).toBe(1);
    expect(stored.entries).toHaveLength(2);
    expect(stored.entries[0]).toMatchObject({ kind: "user", text: "Phiên tới có tăng không?" });
    expect(typeof stored.entries[0].at).toBe("string");
    expect(stored.entries[1].response.request_id).toBe("req-luu");

    cleanup();
    renderAs(signedIn("sub-a"));
    expect(screen.getByText("Phiên tới có tăng không?")).toBeInTheDocument();
    expect(screen.getByText(/xác suất tăng 51%/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "EIA tuần này" })).toHaveAttribute("href", "https://www.eia.gov/x");
    expect(screen.getByText("Mã tra cứu: req-luu")).toBeInTheDocument();
    expect(screen.getByText("Còn 17/20 lượt hôm nay")).toBeInTheDocument();
  });

  it("câu hỏi sau khi khôi phục vẫn gửi kèm lịch sử theo luật cũ (tối đa 3 lượt gần nhất)", async () => {
    for (let i = 1; i <= 4; i += 1) fetchMock.mockResolvedValueOnce(jsonResponse(200, reply({ answer: `Đáp ${i}.` })));
    renderAs(signedIn("sub-a"));
    for (let i = 1; i <= 3; i += 1) {
      ask(`Hỏi ${i}?`);
      await screen.findByText(`Đáp ${i}.`);
    }
    cleanup();
    renderAs(signedIn("sub-a"));
    ask("Hỏi 4?");
    await screen.findByText("Đáp 4.");
    expect(sentBody(3).history).toEqual([
      { role: "user", text: "Hỏi 1?" },
      { role: "assistant", text: "Đáp 1." },
      { role: "user", text: "Hỏi 2?" },
      { role: "assistant", text: "Đáp 2." },
      { role: "user", text: "Hỏi 3?" },
      { role: "assistant", text: "Đáp 3." },
    ]);
  });

  it("khóa theo người dùng + tài sản: tài khoản khác và tài sản khác không thấy hội thoại", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, reply({ answer: "Riêng của A." })));
    renderAs(signedIn("sub-a"));
    ask("Hỏi?");
    await screen.findByText("Riêng của A.");
    cleanup();

    renderAs(signedIn("sub-b"));
    expect(screen.queryByText("Riêng của A.")).toBeNull();
    cleanup();
    renderAs(signedIn("sub-a"), "gold");
    expect(screen.queryByText("Riêng của A.")).toBeNull();
    cleanup();
    renderAs(SAMPLE_AUTH);
    expect(screen.queryByText("Riêng của A.")).toBeNull();
  });

  it("chưa biết tài khoản (đang tải) thì chưa đọc; tải xong thì khôi phục đúng khóa", () => {
    window.sessionStorage.setItem(
      chatStorageKey("sub-a", "wti"),
      JSON.stringify({ v: 1, entries: [{ id: 0, at: "", kind: "user", text: "Câu cũ" }] }),
    );
    const loading: AuthState = { ...signedIn("sub-a"), account: null };
    const view = renderAs(loading);
    expect(screen.queryByText("Câu cũ")).toBeNull();
    view.rerender(
      <AuthContext.Provider value={signedIn("sub-a")}>
        <ChatPanel asset="wti" assetName="Dầu WTI" />
      </AuthContext.Provider>,
    );
    expect(screen.getByText("Câu cũ")).toBeInTheDocument();
  });

  it("đóng phiên (sessionStorage bị xóa) thì hội thoại mất", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, reply({ answer: "Tạm thời." })));
    renderAs(signedIn("sub-a"));
    ask("Hỏi?");
    await screen.findByText("Tạm thời.");
    cleanup();
    window.sessionStorage.clear();
    renderAs(signedIn("sub-a"));
    expect(screen.queryByText("Tạm thời.")).toBeNull();
  });

  it("dữ liệu lưu bị hỏng: bỏ qua, khung chat vẫn dùng được", () => {
    window.sessionStorage.setItem(chatStorageKey("sub-a", "wti"), "{không phải json");
    renderAs(signedIn("sub-a"));
    expect(screen.getByLabelText("Câu hỏi cho chatbot")).toBeEnabled();
    expect(window.sessionStorage.getItem(chatStorageKey("sub-a", "wti"))).toBeNull();
    expect(Object.keys(window.sessionStorage).every((k) => !k.startsWith(CHAT_STORAGE_PREFIX))).toBe(true);
  });
});
