import { Link } from "react-router-dom";
import { config } from "../api/config";
import { DISCLAIMER_TEXT } from "../components/Disclaimer";

export default function About() {
  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-2xl font-bold">Giới thiệu</h1>
      <p className="text-sm">
        CPAWS dự báo khoảng giá và xác suất tăng của vàng, bạc, dầu Brent và dầu WTI trong 1–7 phiên giao
        dịch tới, hiển thị theo USD hoặc VND.
      </p>
      <h2 className="text-lg font-semibold">Cách đọc dự báo</h2>
      <ul className="list-disc space-y-2 pl-5 text-sm">
        <li>
          Dự báo là các phân vị của <strong>log return</strong>, quy đổi sang khoảng giá. Khoảng 80% (q10–q90)
          nghĩa là giá được kỳ vọng nằm trong khoảng đó với xác suất danh nghĩa 80%.
        </li>
        <li>
          Xác suất tăng lấy đúng số hệ thống tính, làm tròn đến 1% và giới hạn trong 5%–95% (ghi “≥ 95%” hoặc
          “≤ 5%” ở hai đầu). Nhãn “Nghiêng tăng” khi xác suất tăng từ 60%, “Nghiêng giảm” khi từ 40% trở xuống,
          còn lại là “Chưa rõ xu hướng”; nhãn luôn ghi kèm số phiên.
        </li>
        <li>
          {config.showMetalPrices
            ? "Vàng và bạc dùng chuỗi đại diện GLD, SLV quy đổi về USD/oz; đây không phải giá giao ngay. Giá vàng đổi sang VND/lượng không phải giá vàng miếng trong nước."
            : "Vàng và bạc là dự báo dựa trên chuỗi đại diện GLD, SLV; web chỉ hiển thị % thay đổi và xác suất tăng, không hiển thị giá."}
        </li>
        <li>Giá dầu là hợp đồng tương lai; kỳ dự báo có thể chứa ngày đáo hạn hợp đồng.</li>
      </ul>

      <h2 className="text-lg font-semibold">Phương pháp</h2>
      <ul className="list-disc space-y-2 pl-5 text-sm">
        <li>
          Dự báo hiện dùng <strong>mốc thống kê 252 phiên</strong>: với mỗi số phiên h = 1…7, các phân vị lấy
          từ phân phối thực nghiệm của return h phiên trong 252 phiên giao dịch gần nhất (khoảng 1 năm), chỉ
          dùng các return đã hoàn tất trước ngày dự báo. Không dùng mô hình học máy.
        </li>
        <li>
          Cách làm này đã được chạy lại trên dữ liệu năm 2019 (<strong>kiểm định lịch sử 2019</strong>). Kết quả
          kiểm định lịch sử tách riêng, không so trực tiếp với số đo chạy thật ở trang{" "}
          <Link to="/accuracy" className="text-forecast underline">
            Độ chính xác
          </Link>
          .
        </li>
      </ul>
      <p className="text-sm font-medium">{DISCLAIMER_TEXT}</p>
    </div>
  );
}
