import { EmptyBlock } from "../components/StateViews";

// KHUNG trang độ chính xác. GET /accuracy/{asset} do Long làm ở tuần 3 (docs/api/contract.md, mục "Thêm sau").
// Cố ý KHÔNG hiển thị số liệu mẫu ở đây: chưa có kết quả chạy thật thì không bịa con số độ chính xác.
const METRICS: { name: string; meaning: string }[] = [
  {
    name: "Pinball skill",
    meaning: "1 − pinball loss của mô hình / của mốc 252 phiên. Lớn hơn 0 nghĩa là tốt hơn mốc so sánh.",
  },
  {
    name: "Độ phủ khoảng 80% (coverage_80)",
    meaning: "Tỷ lệ lần giá trị thực nằm trong [q10, q90]; mục tiêu 80%. Đi kèm độ rộng khoảng.",
  },
  {
    name: "Brier skill",
    meaning: "So Brier score của xác suất tăng với tần suất tăng 252 phiên gần nhất. Lớn hơn 0 là tốt hơn.",
  },
  {
    name: "Tỷ lệ đúng chiều (sign_accuracy)",
    meaning: "Chỉ có ý nghĩa khi đọc cùng tỷ lệ phiên tăng thực tế (up_rate).",
  },
  {
    name: "Tỷ lệ MAE so với naive",
    meaning: "MAE của trung vị / MAE của naive (return = 0). Nhỏ hơn 1 là tốt hơn naive.",
  },
];

export default function Accuracy() {
  return (
    <div>
      <h1 className="text-2xl font-bold">Độ chính xác</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted">
        Đánh giá trên 8 tuần gần nhất của dự báo chạy thật, tính riêng từng h trên log return và luôn so với
        naive. Không dùng MAPE trên mức giá.
      </p>

      <div className="mt-6">
        <EmptyBlock title="Chưa có dữ liệu chạy thật">
          Số liệu sẽ hiển thị khi endpoint /accuracy sẵn sàng (dự kiến tuần 3) và hệ thống đã tích lũy dự
          báo đủ lâu để so với giá thực.
        </EmptyBlock>
      </div>

      <h2 className="mt-8 text-lg font-semibold">Các chỉ số sẽ hiển thị</h2>
      <dl className="mt-3 divide-y divide-line rounded-lg border border-line bg-white">
        {METRICS.map((metric) => (
          <div key={metric.name} className="px-4 py-3">
            <dt className="text-sm font-medium">{metric.name}</dt>
            <dd className="mt-0.5 text-sm text-muted">{metric.meaning}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
