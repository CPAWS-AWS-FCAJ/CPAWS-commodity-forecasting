import type { ReactNode } from "react";

export function LoadingBlock({ label = "Đang tải…" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="rounded-lg border border-line bg-surface p-6 text-sm text-muted">
      {label}
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
