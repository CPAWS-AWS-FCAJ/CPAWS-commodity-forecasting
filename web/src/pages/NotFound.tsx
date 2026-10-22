import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div>
      <h1 className="text-2xl font-bold">Không tìm thấy trang</h1>
      <p className="mt-2 text-sm text-muted">Đường dẫn không đúng hoặc sản phẩm không tồn tại.</p>
      <p className="mt-4">
        <Link to="/" className="text-forecast underline">
          Về trang chủ
        </Link>
      </p>
    </div>
  );
}
