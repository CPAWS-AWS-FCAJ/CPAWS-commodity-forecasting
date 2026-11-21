import { Authenticator } from "@aws-amplify/ui-react";
import "@aws-amplify/ui-react/styles.css";
import { signUp } from "aws-amplify/auth";
import type { SignUpInput } from "aws-amplify/auth";
import { I18n } from "aws-amplify/utils";
import { config } from "../api/config";
import {
  FORM_FIELDS,
  NAME_REQUIRED_MESSAGE,
  normalizeName,
  PASSWORD_HINT,
  SIGN_UP_ATTRIBUTES,
  validateSignUpName,
  VI_VOCABULARY,
} from "./authForm";
import "./amplify";
import "./amplify-theme.css";

// Nhãn tiếng Việt cho Authenticator (Amplify UI chưa có bản dịch vi).
I18n.putVocabulariesForLanguage("vi", VI_VOCABULARY);
I18n.setLanguage("vi");

/** Gửi Họ tên đã bỏ khoảng trắng thừa; rỗng thì chặn (lỗi hiện dưới form). */
const handleSignUp = (async (input: SignUpInput) => {
  const attributes = input.options?.userAttributes ?? {};
  const name = normalizeName(attributes.name);
  if (!name) throw new Error(NAME_REQUIRED_MESSAGE);
  return signUp({
    ...input,
    options: { ...input.options, userAttributes: { ...attributes, name } },
  });
  // signUp có thêm chữ ký (ctx, input) cho SSR; Authenticator chỉ gọi dạng (input).
}) as typeof signUp;

export const SIGN_IN_SERVICES = {
  async validateCustomSignUp(formData: Record<string, string>, touchData: Record<string, boolean>) {
    return validateSignUpName(formData, touchData) ?? undefined;
  },
  handleSignUp,
};

const components = {
  SignUp: {
    FormFields() {
      return (
        <>
          <Authenticator.SignUp.FormFields />
          <p className="text-sm text-muted">{PASSWORD_HINT}</p>
        </>
      );
    },
  },
};

export type AuthTab = "signIn" | "signUp";

/**
 * Form Cognito (tab Đăng nhập/Đăng ký, xác minh email bằng mã, quên mật khẩu). Dùng lại Provider ở
 * AmplifyAuthProvider; khi đăng nhập xong trang /dang-nhap tự chuyển về `next`.
 */
export default function SignInPanel({ initialState = "signIn" }: { initialState?: AuthTab }) {
  // Tab Đăng ký chỉ hiện khi pool cho tự đăng ký và bản build bật VITE_ALLOW_SIGNUP.
  const allowSignUp = config.allowSignUp;
  return (
    <Authenticator
      initialState={allowSignUp ? initialState : "signIn"}
      hideSignUp={!allowSignUp}
      signUpAttributes={[...SIGN_UP_ATTRIBUTES]}
      formFields={FORM_FIELDS}
      services={SIGN_IN_SERVICES}
      components={components}
    />
  );
}
