import { cleanup, render } from "@testing-library/react";
import type { SignUpInput } from "aws-amplify/auth";
import { NAME_REQUIRED_MESSAGE } from "./authForm";

const flags = vi.hoisted(() => ({ allowSignUp: true }));
const captured = vi.hoisted(() => ({ props: {} as Record<string, unknown> }));
const amplify = vi.hoisted(() => ({
  signUp: vi.fn(async (input: unknown) => ({ input })),
  // Gọi lúc import module (trước các test): ghi lại bằng mảng, không dùng mock.calls (bị xóa giữa test).
  i18n: [] as unknown[][],
}));

vi.mock("../api/config", () => ({
  config: {
    get allowSignUp() {
      return flags.allowSignUp;
    },
  },
}));
// Không cấu hình Amplify thật trong test.
vi.mock("./amplify", () => ({}));
vi.mock("aws-amplify/auth", () => ({ signUp: amplify.signUp }));
vi.mock("aws-amplify/utils", () => ({
  I18n: {
    putVocabulariesForLanguage: (...args: unknown[]) => amplify.i18n.push(["putVocabulariesForLanguage", ...args]),
    setLanguage: (...args: unknown[]) => amplify.i18n.push(["setLanguage", ...args]),
  },
}));
vi.mock("@aws-amplify/ui-react", () => {
  const Authenticator = (props: Record<string, unknown>) => {
    captured.props = props;
    return null;
  };
  Authenticator.SignUp = { FormFields: () => null };
  return { Authenticator };
});

const { default: SignInPanel, SIGN_IN_SERVICES } = await import("./SignInPanel");

afterEach(() => {
  cleanup();
  captured.props = {};
});

describe("SignInPanel (Authenticator)", () => {
  it("đặt tiếng Việt cho Authenticator", () => {
    const vocab = amplify.i18n.find(([name]) => name === "putVocabulariesForLanguage");
    expect(vocab?.[1]).toBe("vi");
    expect(vocab?.[2]).toEqual(expect.objectContaining({ "Sign In": "Đăng nhập" }));
    expect(amplify.i18n).toContainEqual(["setLanguage", "vi"]);
  });

  it("cho tự đăng ký: hiện tab Đăng ký với email + name và formFields tiếng Việt", () => {
    flags.allowSignUp = true;
    render(<SignInPanel initialState="signUp" />);
    expect(captured.props.hideSignUp).toBe(false);
    expect(captured.props.initialState).toBe("signUp");
    expect(captured.props.signUpAttributes).toEqual(["email", "name"]);
    const formFields = captured.props.formFields as Record<string, Record<string, { label: string }>>;
    expect(formFields.signUp.name.label).toBe("Họ và tên");
    expect(formFields.signUp.confirm_password.label).toBe("Nhập lại mật khẩu");
    expect(formFields.signUp.phone_number).toBeUndefined();
  });

  it("không cho tự đăng ký: ẩn tab Đăng ký, luôn mở tab Đăng nhập", () => {
    flags.allowSignUp = false;
    render(<SignInPanel initialState="signUp" />);
    expect(captured.props.hideSignUp).toBe(true);
    expect(captured.props.initialState).toBe("signIn");
  });

  it("gửi Họ tên đã bỏ khoảng trắng thừa; Họ tên rỗng thì không gọi Cognito", async () => {
    const input = {
      username: "lan01",
      password: "Abcdef1!",
      options: { userAttributes: { email: "lan@example.com", name: "  Nguyễn  Thị Lan " } },
    } as SignUpInput;
    await SIGN_IN_SERVICES.handleSignUp(input);
    expect(amplify.signUp).toHaveBeenCalledWith(
      expect.objectContaining({
        options: { userAttributes: { email: "lan@example.com", name: "Nguyễn Thị Lan" } },
      }),
    );

    amplify.signUp.mockClear();
    const blank = { ...input, options: { userAttributes: { email: "lan@example.com", name: "   " } } } as SignUpInput;
    await expect(SIGN_IN_SERVICES.handleSignUp(blank)).rejects.toThrow(NAME_REQUIRED_MESSAGE);
    expect(amplify.signUp).not.toHaveBeenCalled();
  });

  it("validateCustomSignUp báo lỗi Họ tên toàn khoảng trắng", async () => {
    await expect(SIGN_IN_SERVICES.validateCustomSignUp({ name: "  " }, { name: true })).resolves.toEqual({
      name: NAME_REQUIRED_MESSAGE,
    });
    await expect(SIGN_IN_SERVICES.validateCustomSignUp({ name: "Lan" }, { name: true })).resolves.toBeUndefined();
  });
});
