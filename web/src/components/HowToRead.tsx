import type { ReactNode } from "react";
import { Link, useInRouterContext } from "react-router-dom";

/**
 * Anchor của trang "Cách đọc dự báo" (/guide). Đặt ở đây, không ở pages/Guide.tsx, để các khối trên
 * trang sản phẩm link tới mà không kéo cả trang hướng dẫn vào bundle.
 */
export const GUIDE_ANCHORS = {
  chart: "doc-bieu-do",
  logReturn: "log-return",
  horizon: "so-phien",
  quantiles: "phan-vi",
  interval: "khoang-80",
  probUp: "xac-suat-tang",
  baseline: "moc-252",
  reliability: "do-tin-cay",
  roll: "dao-han",
  sources: "nguon-du-lieu",
  vnd: "quy-doi-vnd",
} as const;

export type GuideAnchor = (typeof GUIDE_ANCHORS)[keyof typeof GUIDE_ANCHORS];

export function guideHref(anchor: GuideAnchor): string {
  return `/guide#${anchor}`;
}

const LINK_CLASS = "whitespace-nowrap text-forecast underline underline-offset-2";

/**
 * Link "Tìm hiểu thêm" tới một mục của trang hướng dẫn; phần sau đọc cho trình đọc màn hình. Ngoài
 * Router (component render riêng trong test) thì dùng thẻ <a> thường.
 */
export function GuideLink({ anchor, topic }: { anchor: GuideAnchor; topic: string }) {
  const inRouter = useInRouterContext();
  const label = (
    <>
      Tìm hiểu thêm<span className="sr-only"> về {topic}</span>
    </>
  );
  return inRouter ? (
    <Link to={guideHref(anchor)} className={LINK_CLASS}>
      {label}
    </Link>
  ) : (
    <a href={guideHref(anchor)} className={LINK_CLASS}>
      {label}
    </a>
  );
}

/** 1–2 câu "Cách đọc" đặt ngay dưới tiêu đề một khối, kèm link tới trang hướng dẫn. */
export function HowToRead({
  anchor,
  topic,
  children,
  className = "mt-1",
}: {
  anchor: GuideAnchor;
  /** Chủ đề của link, ví dụ "biểu đồ giá và dự báo". */
  topic: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <p className={`max-w-3xl text-sm text-muted ${className}`.trim()}>
      <span className="font-medium text-price">Cách đọc: </span>
      {children} <GuideLink anchor={anchor} topic={topic} />
    </p>
  );
}
