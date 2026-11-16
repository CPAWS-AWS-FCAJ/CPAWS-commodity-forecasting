import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import AuthGate from "./AuthGate";

const flags = vi.hoisted(() => ({ allowSignUp: false }));
const captured = vi.hoisted(() => ({ props: {} as Record<string, unknown> }));

vi.mock("../api/config", () => ({
  config: {
    get allowSignUp() {
      return flags.allowSignUp;
    },
  },
}));
// Không cấu hình Amplify thật trong test.
vi.mock("./amplify", () => ({}));
vi.mock("aws-amplify/auth", () => ({ signOut: vi.fn() }));
vi.mock("@aws-amplify/ui-react", () => ({
  Authenticator: (props: { children: () => ReactNode } & Record<string, unknown>) => {
    captured.props = props;
    return <>{props.children()}</>;
  },
}));

describe("AuthGate", () => {
  beforeEach(() => {
    captured.props = {};
  });

  it("ẩn đăng ký khi VITE_ALLOW_SIGNUP không bật (mặc định)", () => {
    flags.allowSignUp = false;
    render(<AuthGate>nội dung</AuthGate>);
    expect(screen.getByText("nội dung")).toBeInTheDocument();
    expect(captured.props.hideSignUp).toBe(true);
  });

  it("hiện đăng ký với email bắt buộc khi VITE_ALLOW_SIGNUP=true", () => {
    flags.allowSignUp = true;
    render(<AuthGate>nội dung</AuthGate>);
    expect(captured.props.hideSignUp).toBe(false);
    expect(captured.props.signUpAttributes).toEqual(["email"]);
  });
});
