import { lazy, Suspense } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { config } from "../api/config";
import { useAuth } from "../auth/AuthContext";
import { safeNextPath, SIGN_UP_TAB } from "../auth/redirect";
import { PublicShell } from "../components/shell/PublicChrome";
import { LoadingBlock } from "../components/StateViews";

// Authenticator kéo theo aws-amplify: chỉ tải khi mở trang này với đăng nhập bật.
const SignInPanel = lazy(() => import("../auth/SignInPanel"));

const AFTER_SIGN_IN = [
  "Khoảng giá 80% và xác suất tăng 1–7 phiên của vàng, bạc, dầu Brent và WTI",
  "Tổng quan giá theo USD hoặc VND",
  "Độ chính xác đo lại trên các dự báo đã chạy",
  "Chatbot tiếng Việt giải thích dự báo, có trích nguồn",
];

/**
 * /dang-nhap?next=<đường dẫn>[&tab=dang-ky]: form Cognito (tab Đăng nhập/Đăng ký). Đăng nhập xong
 * (hoặc đã đăng nhập sẵn, hoặc chạy dữ liệu mẫu) thì quay về `next`, chỉ nhận đường dẫn nội bộ.
 */
export default function SignIn() {
  const { status } = useAuth();
  const [params] = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const wantsSignUp = config.allowSignUp && params.get("tab") === SIGN_UP_TAB;

  if (status === "authenticated") return <Navigate to={next} replace />;

  return (
    <PublicShell showAuthActions={false}>
      {/* Điện thoại: tiêu đề → form → danh sách lợi ích (form vẫn ở màn đầu). Máy tính: hai cột như cũ,
          danh sách nằm dưới tiêu đề ở cột trái. */}
      <div className="mx-auto grid max-w-6xl items-start gap-6 px-4 py-8 sm:px-6 lg:grid-cols-[minmax(0,1fr)_28rem] lg:grid-rows-[auto_1fr] lg:gap-x-10 lg:gap-y-8 lg:px-10 lg:py-16">
        <section className="max-w-lg lg:col-start-1 lg:row-start-1">
          <h1 className="text-3xl font-semibold tracking-tight">
            {config.allowSignUp ? "Đăng nhập hoặc tạo tài khoản" : "Đăng nhập để xem dự báo"}
          </h1>
          <p className="mt-3 text-muted">
            Giá và khoảng dự báo chỉ hiện sau khi đăng nhập.{" "}
            {config.allowSignUp
              ? "Tài khoản dùng tên đăng nhập và mật khẩu; email chỉ để nhận mã xác minh."
              : "Tài khoản do nhóm CPAWS cấp."}
          </p>
        </section>
        <div className="w-full lg:col-start-2 lg:row-span-2 lg:row-start-1">
          {status === "loading" ? (
            <LoadingBlock label="Đang kiểm tra đăng nhập…" />
          ) : (
            <Suspense fallback={<LoadingBlock label="Đang tải form đăng nhập…" />}>
              <SignInPanel initialState={wantsSignUp ? "signUp" : "signIn"} />
            </Suspense>
          )}
        </div>
        <section aria-labelledby="after-sign-in" className="max-w-lg lg:col-start-1 lg:row-start-2">
          <h2 id="after-sign-in" className="text-sm font-medium">
            Sau khi đăng nhập
          </h2>
          <ul className="mt-3 space-y-2 text-sm text-muted">
            {AFTER_SIGN_IN.map((line) => (
              <li key={line} className="flex gap-3">
                <span aria-hidden="true" className="mt-2 h-px w-3 shrink-0 bg-muted" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </PublicShell>
  );
}
