import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { AuthProvider } from "./auth/AuthProvider";
import { RequireAuth } from "./auth/RequireAuth";
import { Layout } from "./components/Layout";
import { LoadingBlock } from "./components/StateViews";
import About from "./pages/About";
import Accuracy from "./pages/Accuracy";
import Home from "./pages/Home";
import Landing from "./pages/Landing";
import NotFound from "./pages/NotFound";
import SignIn from "./pages/SignIn";

// Trang sản phẩm kéo theo Recharts (nặng), nạp muộn để trang chủ tải nhanh.
const AssetPage = lazy(() => import("./pages/AssetPage"));
const Overview = lazy(() => import("./pages/Overview"));
const Guide = lazy(() => import("./pages/Guide"));

function Lazy({ label, children }: { label: string; children: ReactNode }) {
  return <Suspense fallback={<LoadingBlock label={label} />}>{children}</Suspense>;
}

/**
 * Khung chung cho mọi trang app (một Layout duy nhất, sidebar không bị dựng lại khi đổi trang).
 * Riêng "/" khi chưa đăng nhập là trang giới thiệu công khai, không có số giá và không gọi API dự
 * báo (ADR-0005); đã đăng nhập (hoặc chạy dữ liệu mẫu) thì "/" là trang chủ dự báo.
 */
function AppFrame() {
  const { status } = useAuth();
  const { pathname } = useLocation();
  if (pathname === "/" && status === "unauthenticated") return <Landing />;
  if (pathname === "/" && status === "loading") {
    return (
      <div className="mx-auto max-w-6xl px-4 py-10">
        <LoadingBlock label="Đang kiểm tra đăng nhập…" />
      </div>
    );
  }
  return <Layout />;
}

/**
 * Định tuyến: công khai (/, /guide, /about, /dang-nhap) và cần đăng nhập (/overview, /asset/:id,
 * /accuracy → /dang-nhap?next=… khi chưa đăng nhập).
 */
export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="dang-nhap" element={<SignIn />} />
        <Route element={<AppFrame />}>
          <Route index element={<Home />} />
          <Route
            path="guide"
            element={
              <Lazy label="Đang tải hướng dẫn…">
                <Guide />
              </Lazy>
            }
          />
          <Route path="about" element={<About />} />
          <Route element={<RequireAuth />}>
            <Route
              path="overview"
              element={
                <Lazy label="Đang tải tổng quan giá…">
                  <Overview />
                </Lazy>
              }
            />
            <Route
              path="asset/:id"
              element={
                <Lazy label="Đang tải trang sản phẩm…">
                  <AssetPage />
                </Lazy>
              }
            />
            <Route path="accuracy" element={<Accuracy />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}
