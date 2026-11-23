import { LockIcon } from "./icons";

/**
 * Ổ khóa cạnh link tới trang cần đăng nhập (dùng ở trang công khai, 404, Giới thiệu): icon cho mắt
 * nhìn, chữ "(cần đăng nhập)" cho trình đọc màn hình. Cùng cách hiển thị với mục khóa ở sidebar.
 */
export function LockMark({ className = "" }: { className?: string }) {
  return (
    <>
      <LockIcon className={`text-muted ${className}`.trim()} />
      <span className="sr-only">(cần đăng nhập)</span>
    </>
  );
}
