import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

/**
 * Đổi số liệu bằng một nhịp mờ-hiện ngắn (160ms) khi `value` đổi (đổi USD/VND, đổi số phiên), để mắt
 * thấy số vừa đổi mà không phải chờ: không đếm số chạy. Lần hiển thị đầu không chạy hiệu ứng.
 * Chỉ đổi opacity nên không xô lệch bố cục; giảm chuyển động thì đổi tức thì (index.css).
 */
export function Swap({
  value,
  children,
  className = "",
}: {
  /** Khóa nội dung: đổi khóa thì phần bên trong hiện lại bằng hiệu ứng. */
  value: string;
  children: ReactNode;
  className?: string;
}) {
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
  }, []);
  return (
    <span key={value} className={`${mounted.current ? "animate-swap " : ""}${className}`.trim() || undefined}>
      {children}
    </span>
  );
}
