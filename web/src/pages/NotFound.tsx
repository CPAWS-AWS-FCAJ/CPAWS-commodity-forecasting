import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="max-w-xl">
      <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Không tìm thấy trang</h1>
      <p className="mt-2 text-sm text-muted">Đường dẫn không đúng hoặc sản phẩm không tồn tại.</p>
      <div className="mt-6 flex flex-wrap gap-4 text-sm font-medium">
        <Link to="/" className="text-forecast underline-offset-4 hover:underline">
          Về trang chủ
        </Link>
        <Link to="/guide" className="text-forecast underline-offset-4 hover:underline">
          Cách đọc dự báo
        </Link>
      </div>
    </div>
  );
}
