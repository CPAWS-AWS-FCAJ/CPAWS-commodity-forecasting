import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ChatResponse } from "../api/types";
import { AuthContext, SAMPLE_AUTH } from "../auth/AuthContext";
import SignOutButton from "../auth/SignOutButton";
import {
  CHAT_STORAGE_PREFIX,
  chatStorageKey,
  clearChatHistory,
  loadChat,
  MAX_STORED_CHARS,
  MAX_STORED_ENTRIES,
  saveChat,
  type ChatEntry,
} from "./chatHistory";

const response = (answer: string): ChatResponse => ({
  request_id: "r",
  answer,
  branch: "complex",
  prompt_version: "v2",
  forecasts_used: [{ asset: "wti", base_date: "2026-11-20", model_version: "baseline-q252", is_sample: false, stale: false }],
  citations: [],
  truncated: false,
  blocked: false,
  quota: null,
  disclaimer: "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư.",
});

/** n lượt hỏi đáp: id 0,1 là lượt 1, id 2,3 là lượt 2… */
function turns(n: number, answer = (i: number) => `Đáp ${i}`): ChatEntry[] {
  return Array.from({ length: n }, (_, i) => [
    { id: i * 2, at: "2026-11-23T00:00:00Z", kind: "user" as const, text: `Hỏi ${i}` },
    { id: i * 2 + 1, at: "2026-11-23T00:00:01Z", kind: "assistant" as const, response: response(answer(i)) },
  ]).flat();
}

beforeEach(() => window.sessionStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("chatHistory", () => {
  const key = chatStorageKey("sub-a", "wti");

  it("khóa có tiền tố phiên bản, người dùng và tài sản", () => {
    expect(key).toBe("cpaws.chat.v1:sub-a:wti");
  });

  it("lưu rồi đọc lại đúng nội dung; danh sách rỗng thì xóa khóa", () => {
    const entries = [...turns(1), { id: 2, at: "", kind: "error" as const, text: "Hết lượt", resetAt: "2026-11-24T17:00:00Z" }];
    saveChat(key, entries);
    expect(loadChat(key)).toEqual(entries);
    saveChat(key, []);
    expect(window.sessionStorage.getItem(key)).toBeNull();
  });

  it("giữ tối đa 30 lượt gần nhất, bắt đầu bằng câu hỏi", () => {
    saveChat(key, turns(40));
    const loaded = loadChat(key);
    expect(loaded).toHaveLength(MAX_STORED_ENTRIES);
    expect(loaded[0]).toMatchObject({ kind: "user", text: "Hỏi 10" });
    expect(loaded.at(-1)).toMatchObject({ kind: "assistant" });
  });

  it("quá kích thước thì bỏ dần lượt cũ nhất", () => {
    const long = "x".repeat(Math.floor(MAX_STORED_CHARS / 4));
    saveChat(key, turns(6, () => long));
    const raw = window.sessionStorage.getItem(key)!;
    expect(raw.length).toBeLessThanOrEqual(MAX_STORED_CHARS);
    const loaded = loadChat(key);
    expect(loaded.length).toBeGreaterThan(0);
    expect(loaded[0].kind).toBe("user");
    expect(loaded.at(-1)).toMatchObject({ id: 11 });
  });

  it("dữ liệu hỏng: JSON sai, sai phiên bản → [] và xóa khóa; lượt sai dạng bị bỏ", () => {
    window.sessionStorage.setItem(key, "{oops");
    expect(loadChat(key)).toEqual([]);
    expect(window.sessionStorage.getItem(key)).toBeNull();

    window.sessionStorage.setItem(key, JSON.stringify({ v: 99, entries: [] }));
    expect(loadChat(key)).toEqual([]);

    window.sessionStorage.setItem(
      key,
      JSON.stringify({
        v: 1,
        entries: [
          { id: 0, at: "", kind: "user", text: "Hỏi" },
          { id: 1, at: "", kind: "assistant", response: { answer: 42 } },
          { id: 2, kind: "user", text: "Hỏi lại" },
          { id: 3, at: "", kind: "assistant", response: { ...response("Đáp"), citations: [{ title: 1 }, { title: "Nguồn", link: "https://a.b" }] } },
          { id: "x", kind: "user", text: "sai id" },
          null,
        ],
      }),
    );
    const loaded = loadChat(key);
    expect(loaded.map((e) => e.id)).toEqual([0, 2, 3]);
    const last = loaded[2];
    expect(last.kind === "assistant" && last.response.citations).toEqual([
      { title: "Nguồn", link: "https://a.b", source: "", published_at: "" },
    ]);
  });

  it("sessionStorage bị chặn (ném lỗi) thì không làm hỏng trang", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => saveChat(key, turns(1))).not.toThrow();
    expect(loadChat(key)).toEqual([]);
    expect(() => clearChatHistory()).not.toThrow();
  });

  it("clearChatHistory xóa mọi hội thoại, giữ khóa khác", () => {
    saveChat(chatStorageKey("sub-a", "wti"), turns(1));
    saveChat(chatStorageKey("sub-b", "gold"), turns(1));
    window.sessionStorage.setItem("khac", "1");
    clearChatHistory();
    expect(Object.keys(window.sessionStorage).filter((k) => k.startsWith(CHAT_STORAGE_PREFIX))).toEqual([]);
    expect(window.sessionStorage.getItem("khac")).toBe("1");
  });
});

describe("Đăng xuất xóa lịch sử chat của phiên", () => {
  it("bấm Đăng xuất (kể cả khi đăng xuất lỗi mạng) thì xóa mọi khóa cpaws.chat.v1:", async () => {
    saveChat(chatStorageKey("sub-a", "wti"), turns(1));
    const signOut = vi.fn().mockRejectedValue(new Error("mạng"));
    render(
      <MemoryRouter>
        <AuthContext.Provider value={{ ...SAMPLE_AUTH, sampleMode: false, signOut }}>
          <SignOutButton />
        </AuthContext.Provider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
    expect(window.sessionStorage.getItem(chatStorageKey("sub-a", "wti"))).toBeNull();
    await waitFor(() => expect(signOut).toHaveBeenCalled());
  });
});
