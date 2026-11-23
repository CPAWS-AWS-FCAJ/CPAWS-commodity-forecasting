import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { LockMark } from "../components/shell/LockMark";

export default function NotFound() {
  const guideLocked = useAuth().status !== "authenticated";
  return (
    <div className="max-w-xl">
      <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Không tìm thấy trang</h1>
      <p className="mt-2 text-sm text-muted">Đường dẫn không đúng hoặc sản phẩm không tồn tại.</p>
      <div className="mt-6 flex flex-wrap gap-4 text-sm font-medium">
        <Link to="/" className="text-forecast underline-offset-4 hover:underline pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center">
          Về trang chủ
        </Link>
        <Link
          to="/guide"
          className="inline-flex items-center gap-1.5 text-forecast underline-offset-4 hover:underline pointer-coarse:min-h-11"
        >
          Cách đọc dự báo
          {guideLocked ? <LockMark /> : null}
        </Link>
      </div>
    </div>
  );
}
