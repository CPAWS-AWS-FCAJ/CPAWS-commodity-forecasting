import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { RequireAuth } from "./auth/RequireAuth";
import { Layout } from "./components/Layout";
import { LoadingBlock } from "./components/StateViews";
import About from "./pages/About";
import Accuracy from "./pages/Accuracy";
import Home from "./pages/Home";
import NotFound from "./pages/NotFound";

// Trang sản phẩm kéo theo Recharts (nặng), nạp muộn để trang chủ tải nhanh.
const AssetPage = lazy(() => import("./pages/AssetPage"));

export default function App() {
  return (
    <RequireAuth>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route
            path="asset/:id"
            element={
              <Suspense fallback={<LoadingBlock label="Đang tải trang sản phẩm…" />}>
                <AssetPage />
              </Suspense>
            }
          />
          <Route path="accuracy" element={<Accuracy />} />
          <Route path="about" element={<About />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </RequireAuth>
  );
}
