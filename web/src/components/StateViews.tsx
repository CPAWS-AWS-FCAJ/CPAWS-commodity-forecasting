import type { ReactNode } from "react";

/**
 * Hình khung chờ (skeleton) theo khối sắp hiện, để chỗ trống có cùng hình dạng (không nhảy bố cục khi dữ
 * liệu tới) và có nhịp sáng-tối chậm báo "đang tải":
 * - "text": chỉ dòng chữ (đăng nhập, form);
 * - "panel": một khối thẻ chung (trang đang nạp, khối độ tin cậy);
 * - "chart": khung biểu đồ;
 * - "asset": trang sản phẩm (thẻ tóm tắt, dải 7 thẻ, biểu đồ).
 */
export type LoadingShape = "text" | "panel" | "chart" | "asset";

function SkeletonPanel({ lines = 3 }: { lines?: number }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-5 sm:p-6">
      <div className="skeleton h-5 w-40" />
      <div className="skeleton mt-5 h-8 w-56 max-w-full" />
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className={`skeleton mt-3 h-3.5 ${i % 2 ? "w-2/3" : "w-5/6"}`} />
      ))}
    </div>
  );
}

function SkeletonChart() {
  return (
    <div className="rounded-lg border border-line bg-surface p-4 sm:p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="skeleton h-5 w-48 max-w-[60%]" />
        <div className="skeleton h-8 w-40 max-w-[35%]" />
      </div>
      <div className="skeleton mt-5 h-64 w-full sm:h-80" />
    </div>
  );
}

export function LoadingBlock({ label = "Đang tải…", shape = "text" }: { label?: string; shape?: LoadingShape }) {
  if (shape === "text") {
    return (
      <div role="status" aria-live="polite" className="rounded-lg border border-line bg-surface p-6 text-sm text-muted">
        {label}
      </div>
    );
  }
  // Chữ trạng thái vẫn có cho trình đọc màn hình (sr-only), hình khung chỉ để nhìn
  return (
    <div role="status" aria-live="polite" className="animate-fade-in">
      <span className="sr-only">{label}</span>
      <div aria-hidden="true">
        {shape === "panel" ? <SkeletonPanel /> : null}
        {shape === "chart" ? <SkeletonChart /> : null}
        {shape === "asset" ? (
          <div className="space-y-6">
            <SkeletonPanel lines={2} />
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(13rem,1fr))]">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-40 rounded-lg border border-line bg-surface p-4">
                  <div className="skeleton h-4 w-24" />
                  <div className="skeleton mt-3 h-5 w-28" />
                  <div className="skeleton mt-6 h-4 w-32 max-w-full" />
                </div>
              ))}
            </div>
            <SkeletonChart />
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-line bg-surface p-6">
      <p className="text-sm font-medium text-down">Không tải được dữ liệu</p>
      <p className="mt-1 text-sm text-muted">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-price transition-colors duration-150 hover:bg-surface-muted active:bg-line"
        >
          Thử lại
        </button>
      ) : null}
    </div>
  );
}

export function EmptyBlock({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line bg-surface p-6">
      <p className="text-sm font-medium">{title}</p>
      {children ? <div className="mt-1 text-sm text-muted">{children}</div> : null}
    </div>
  );
}
