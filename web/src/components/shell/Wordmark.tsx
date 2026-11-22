import { Link } from "react-router-dom";

/** Tên sản phẩm dạng chữ, không có logo trang trí. */
export function Wordmark({ onClick, withTagline = false }: { onClick?: () => void; withTagline?: boolean }) {
  return (
    <Link
      to="/"
      onClick={onClick}
      className="inline-flex flex-col justify-center rounded-md leading-none text-price pointer-coarse:min-h-11"
      aria-label="CPAWS, về trang chủ"
    >
      <span className="text-base font-semibold tracking-tight">CPAWS</span>
      {withTagline ? (
        <span className="mt-1 text-xs font-normal text-muted">Dự báo vàng, bạc, dầu</span>
      ) : null}
    </Link>
  );
}
