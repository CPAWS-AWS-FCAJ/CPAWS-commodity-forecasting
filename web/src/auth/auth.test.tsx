import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { UNAUTHORIZED_EVENT } from "../api/client";
import { displayName } from "./AuthContext";
import {
  FORM_FIELDS,
  NAME_REQUIRED_MESSAGE,
  normalizeName,
  PASSWORD_POLICY,
  SIGN_UP_ATTRIBUTES,
  USERNAME_SPACE_MESSAGE,
  validateSignUpFields,
  validateSignUpName,
  validateSignUpUsername,
  VI_VOCABULARY,
} from "./authForm";
import { safeNextPath, signInPath } from "./redirect";
import { useUnauthorizedRedirect } from "./useUnauthorizedRedirect";

afterEach(() => cleanup());

describe("safeNextPath: chỉ nhận đường dẫn nội bộ", () => {
  it.each([
    ["/overview", "/overview"],
    ["/asset/gold?h=3#bang", "/asset/gold?h=3#bang"],
    ["/", "/"],
  ])("%s → %s", (raw, expected) => {
    expect(safeNextPath(raw)).toBe(expected);
  });

  it.each([
    null,
    "",
    "overview",
    "https://evil.example/",
    "//evil.example",
    "/\\evil.example",
    "/\t/evil.example",
    "javascript:alert(1)",
    "/dang-nhap",
    "/dang-nhap?next=/overview",
  ])("từ chối %j → /", (raw) => {
    expect(safeNextPath(raw)).toBe("/");
  });

  it("signInPath mã hóa next, bỏ next khi là trang chủ, thêm tab đăng ký", () => {
    expect(signInPath("/asset/gold")).toBe("/dang-nhap?next=%2Fasset%2Fgold");
    expect(signInPath("/")).toBe("/dang-nhap");
    expect(signInPath("//evil.example")).toBe("/dang-nhap");
    expect(signInPath("/overview", { signUp: true })).toBe("/dang-nhap?next=%2Foverview&tab=dang-ky");
  });
});

describe("displayName: Họ tên → email → tên đăng nhập", () => {
  it("ưu tiên Họ tên", () => {
    expect(displayName({ name: "Nguyễn Thị Lan", email: "lan@example.com", username: "lan01" })).toBe(
      "Nguyễn Thị Lan",
    );
  });
  it("tài khoản cũ không có name (hoặc chỉ khoảng trắng) → email", () => {
    expect(displayName({ email: "lan@example.com", username: "lan01" })).toBe("lan@example.com");
    expect(displayName({ name: "   ", email: "lan@example.com", username: "lan01" })).toBe("lan@example.com");
  });
  it("chỉ còn tên đăng nhập thì mới hiện tên đăng nhập", () => {
    expect(displayName({ username: "lan01" })).toBe("lan01");
    expect(displayName(null)).toBeNull();
  });
});

describe("cấu hình form đăng ký", () => {
  it("gửi email và name, không có số điện thoại", () => {
    expect([...SIGN_UP_ATTRIBUTES]).toEqual(["email", "name"]);
    expect(Object.keys(FORM_FIELDS.signUp)).not.toContain("phone_number");
  });

  it("đủ 5 trường theo thứ tự, nhãn tiếng Việt, Họ tên và Email bắt buộc", () => {
    const fields = FORM_FIELDS.signUp;
    const ordered = Object.entries(fields)
      .sort(([, a], [, b]) => (a.order ?? 0) - (b.order ?? 0))
      .map(([key, value]) => [key, value.label]);
    expect(ordered).toEqual([
      ["name", "Họ và tên"],
      ["email", "Email"],
      ["username", "Tên đăng nhập"],
      ["password", "Mật khẩu"],
      ["confirm_password", "Nhập lại mật khẩu"],
    ]);
    expect(fields.name.isRequired).toBe(true);
    expect(fields.email.isRequired).toBe(true);
    expect(fields.email.type).toBe("email");
  });

  it("chính sách mật khẩu khớp pool: 8 ký tự, hoa, thường, số, ký tự đặc biệt", () => {
    expect(PASSWORD_POLICY).toEqual({
      minLength: 8,
      requireLowercase: true,
      requireUppercase: true,
      requireNumbers: true,
      requireSpecialCharacters: true,
    });
  });

  it("Họ tên rỗng hoặc toàn khoảng trắng bị chặn", () => {
    expect(validateSignUpName({ name: "   " }, { name: true })).toEqual({ name: NAME_REQUIRED_MESSAGE });
    expect(validateSignUpName({ name: "" }, { name: true })).toEqual({ name: NAME_REQUIRED_MESSAGE });
    expect(validateSignUpName({ name: "Lan" }, { name: true })).toBeNull();
    // Chưa chạm vào ô thì chưa báo lỗi
    expect(validateSignUpName({ name: "" }, {})).toBeNull();
    expect(normalizeName("  Nguyễn   Thị  Lan ")).toBe("Nguyễn Thị Lan");
    expect(normalizeName(" \t ")).toBeNull();
  });

  it("tên đăng nhập có khoảng trắng bị chặn trước khi gửi Cognito", () => {
    expect(validateSignUpUsername({ username: "lan 01" }, { username: true })).toEqual({
      username: USERNAME_SPACE_MESSAGE,
    });
    expect(validateSignUpUsername({ username: "lan01" }, { username: true })).toBeNull();
    expect(validateSignUpUsername({ username: "lan 01" }, {})).toBeNull();
    expect(validateSignUpFields({ name: " ", username: "a b" }, { name: true, username: true })).toEqual({
      name: NAME_REQUIRED_MESSAGE,
      username: USERNAME_SPACE_MESSAGE,
    });
    expect(validateSignUpFields({ name: "Lan", username: "lan01" }, { name: true, username: true })).toBeNull();
  });

  it("dịch lỗi tiếng Anh của Cognito khi tên đăng nhập sai mẫu và lỗi mật khẩu", () => {
    const cognito =
      "1 validation error detected: Value at 'username' failed to satisfy constraint: Member must satisfy regular expression pattern: [\\p{L}\\p{M}\\p{S}\\p{N}\\p{P}]+";
    expect(VI_VOCABULARY[cognito]).toBe(USERNAME_SPACE_MESSAGE);
    expect(VI_VOCABULARY["An account with the given email already exists."]).toMatch(/Email này/);
    expect(VI_VOCABULARY["Password did not conform with policy: Password not long enough"]).toMatch(/8 ký tự/);
  });

  it("có bản dịch cho tab, nút và lỗi mật khẩu", () => {
    expect(VI_VOCABULARY["Sign In"]).toBe("Đăng nhập");
    expect(VI_VOCABULARY["Create Account"]).toBe("Tạo tài khoản");
    expect(VI_VOCABULARY["Your passwords must match"]).toBe("Hai mật khẩu chưa khớp");
    expect(VI_VOCABULARY["Password must have special characters"]).toBeTruthy();
  });
});

describe("API trả 401 → đăng xuất → /dang-nhap?next=…", () => {
  function Probe({ signOut }: { signOut: () => Promise<void> }) {
    useUnauthorizedRedirect(signOut);
    const location = useLocation();
    return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
  }
  const wrap = (node: ReactNode) => (
    <MemoryRouter initialEntries={["/asset/gold?h=3"]}>{node}</MemoryRouter>
  );

  it("gọi signOut một lần dù nhiều request 401 cùng lúc, rồi về trang đăng nhập giữ next", async () => {
    const signOut = vi.fn(async () => {});
    render(wrap(<Probe signOut={signOut} />));
    act(() => {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    });
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/dang-nhap?next=%2Fasset%2Fgold%3Fh%3D3"),
    );
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it("đăng xuất lỗi (mạng) vẫn về trang đăng nhập", async () => {
    const signOut = vi.fn(async () => {
      throw new Error("network");
    });
    render(wrap(<Probe signOut={signOut} />));
    act(() => {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    });
    await waitFor(() => expect(screen.getByTestId("location").textContent).toMatch(/^\/dang-nhap\?next=/));
  });
});
