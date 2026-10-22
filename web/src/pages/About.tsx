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
          Mô hình dự báo <strong>log return</strong> theo các phân vị 10%, 50%, 90% rồi quy đổi sang khoảng giá
          và xác suất tăng. Khoảng 80% nghĩa là giá được kỳ vọng nằm trong khoảng đó với xác suất danh nghĩa 80%.
        </li>
        <li>
          Xác suất tăng là phép xấp xỉ từ các phân vị, chưa được hiệu chỉnh. Khi cả khoảng 80% nằm cùng một phía
          so với giá hiện tại, web ghi “trên 90%” hoặc “dưới 10%” thay vì con số chính xác hơn.
        </li>
        <li>
          Vàng và bạc dùng chuỗi đại diện GLD, SLV quy đổi về USD/oz; đây không phải giá giao ngay. Giá vàng đổi
          sang VND/lượng không phải giá vàng miếng trong nước.
        </li>
        <li>Giá dầu là hợp đồng tương lai; kỳ dự báo có thể chứa ngày đáo hạn hợp đồng.</li>
      </ul>
      <p className="text-sm font-medium">Thông tin tham khảo, không phải lời khuyên đầu tư.</p>
    </div>
  );
}
