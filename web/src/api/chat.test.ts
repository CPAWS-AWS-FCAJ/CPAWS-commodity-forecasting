import { ApiError } from "./client";
import {
  buildHistory,
  chatErrorMessage,
  countChars,
  displayAnswer,
  formatResetVn,
  MAX_QUESTION_CHARS,
  questionProblem,
  safeLink,
} from "./chat";

describe("countChars / questionProblem", () => {
  it("đếm theo ký tự Unicode sau NFC, không theo byte hay UTF-16", () => {
    expect(countChars("é")).toBe(1); // é tổ hợp → 1 ký tự sau NFC
    expect(countChars("vàng 📈")).toBe(6);
  });

  it("chặn câu rỗng và câu dài quá 500 ký tự (cùng luật với lỗi 400 của server)", () => {
    expect(questionProblem("   ")).toMatch(/chưa nhập/);
    expect(questionProblem("a".repeat(MAX_QUESTION_CHARS))).toBeNull();
    expect(questionProblem(` ${"ạ".repeat(MAX_QUESTION_CHARS)} `)).toBeNull();
    expect(questionProblem("a".repeat(MAX_QUESTION_CHARS + 1))).toMatch(/500/);
  });
});

describe("buildHistory", () => {
  const turn = (n: number) => ({ question: `hỏi ${n}`, answer: `đáp ${n}` });

  it("giữ tối đa 3 lượt gần nhất, từ cũ đến mới, user/assistant xen kẽ", () => {
    const history = buildHistory([turn(1), turn(2), turn(3), turn(4)]);
    expect(history).toHaveLength(6);
    expect(history.map((h) => h.role)).toEqual(["user", "assistant", "user", "assistant", "user", "assistant"]);
    expect(history[0].text).toBe("hỏi 2");
    expect(history[5].text).toBe("đáp 4");
  });

  it("lượt có câu dài quá 2000 ký tự: dừng ở đó, không cắt chữ", () => {
    const long = { question: "hỏi dài", answer: "x".repeat(2001) };
    expect(buildHistory([turn(1), long, turn(3)])).toEqual([
      { role: "user", text: "hỏi 3" },
      { role: "assistant", text: "đáp 3" },
    ]);
    expect(buildHistory([])).toEqual([]);
    // chỉ có khoảng trắng: server coi là rỗng (strip) → cũng dừng
    expect(buildHistory([turn(1), { question: "hỏi", answer: "  \n " }, turn(3)])).toHaveLength(2);
  });
});

describe("safeLink", () => {
  it("chỉ nhận http/https", () => {
    expect(safeLink("https://www.federalreserve.gov/a")).toBe("https://www.federalreserve.gov/a");
    expect(safeLink("http://example.com/x")).toBe("http://example.com/x");
    expect(safeLink("javascript:alert(1)")).toBeNull();
    expect(safeLink("data:text/html,hi")).toBeNull();
    expect(safeLink("không phải link")).toBeNull();
  });
});

describe("formatResetVn", () => {
  it("giờ Việt Nam; chuỗi sai dạng hoặc không phải chuỗi → null", () => {
    expect(formatResetVn("2026-11-03T17:00:00Z")).toBe("00:00 ngày 04/11");
    expect(formatResetVn("không phải ngày")).toBeNull();
    expect(formatResetVn(undefined)).toBeNull();
  });
});

describe("chatErrorMessage", () => {
  it("429 rate_limited: message của server + giờ reset theo giờ Việt Nam", () => {
    const error = new ApiError(429, "rate_limited", "Bạn đã hỏi quá nhiều, thử lại sau.", {
      error: "rate_limited",
      message: "Bạn đã dùng hết 20 lượt hỏi hôm nay.",
      reset_at: "2026-11-03T17:00:00Z",
    });
    const text = chatErrorMessage(error);
    expect(text).toMatch(/^Bạn đã dùng hết 20 lượt hỏi hôm nay\./);
    expect(text).toMatch(/làm mới lúc 00:00 ngày 04\/11 \(giờ Việt Nam\)\.$/);
  });

  it("429 do throttling của API Gateway (thân mặc định) → câu chung", () => {
    const error = new ApiError(429, "http_429", "Bạn đã hỏi quá nhiều, thử lại sau.", {
      message: "Too Many Requests",
    });
    expect(chatErrorMessage(error)).toBe("Bạn đã hỏi quá nhiều, thử lại sau.");
  });

  it("503, 504 và lỗi mạng có câu riêng; 400 dùng message tiếng Việt của server", () => {
    expect(chatErrorMessage(new ApiError(503, "model_unavailable", "x"))).toMatch(/10 giây/);
    expect(chatErrorMessage(new ApiError(504, "timeout", "x"))).toMatch(/quá lâu/);
    expect(chatErrorMessage(new TypeError("Failed to fetch"))).toMatch(/Không kết nối/);
    expect(chatErrorMessage(new ApiError(400, "invalid_history", "Lịch sử hội thoại không hợp lệ."))).toBe(
      "Lịch sử hội thoại không hợp lệ.",
    );
  });
});

describe("displayAnswer", () => {
  it("bỏ các cặp ** khớp trên một dòng", () => {
    expect(displayAnswer("**a** và **b**")).toBe("a và b");
    expect(displayAnswer("Xác suất tăng **53%**.\n- Khoảng 80%: **72–78 USD/bbl**")).toBe(
      "Xác suất tăng 53%.\n- Khoảng 80%: 72–78 USD/bbl",
    );
  });

  it("giữ * đơn, ** lẻ và cặp ** vắt qua hai dòng", () => {
    expect(displayAnswer("2 * 3 = 6")).toBe("2 * 3 = 6");
    expect(displayAnswer("* gạch đầu dòng")).toBe("* gạch đầu dòng");
    expect(displayAnswer("lẻ ** ở đây")).toBe("lẻ ** ở đây");
    expect(displayAnswer("**mở\nđóng**")).toBe("**mở\nđóng**");
  });

  it("HTML trong answer vẫn là chữ sau khi bỏ **", () => {
    expect(displayAnswer("**<b>x</b>**")).toBe("<b>x</b>");
  });
});
