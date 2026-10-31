import { ASSET_IDS } from "../api/types";
import { ReliabilityBlock } from "../components/ReliabilityBlock";
import { ASSETS } from "../lib/assets";

// Độ tin cậy rolling_8w của champion hiện hành theo GET /accuracy/{asset} (docs/api/contract.md).
// Chỉ hiện số khi API cho phép (display_status = ready); trạng thái đang thu thập phải hiện đúng.
const METRICS: { name: string; meaning: string }[] = [
  {
    name: "Giá thực tế nằm trong khoảng 80%",
    meaning: "Tỷ lệ lần giá thực tế nằm trong khoảng dự báo 80% (q10–q90), kèm số cặp đã chấm. Gần 80% là đạt.",
  },
  {
    name: "Độ rộng khoảng 80%",
    meaning: "Độ rộng trung bình của khoảng 80%, tính theo % giá. Hẹp hơn mà vẫn phủ gần 80% là tốt hơn.",
  },
  {
    name: "Đúng chiều tăng/giảm",
    meaning: "Tỷ lệ lần trung vị dự báo cùng chiều với giá thực tế. Luôn đọc cùng tỷ lệ phiên tăng thực tế.",
  },
];

export default function Accuracy() {
  return (
    <div>
      <h1 className="text-2xl font-bold">Độ chính xác</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted">
        Đối chiếu dự báo chạy thật với giá thực tế trong 8 tuần gần nhất, tính trên log return, gộp 7 mức h.
        Không dùng sai số trên mức giá như MAPE.
      </p>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {ASSET_IDS.map((asset) => (
          <ReliabilityBlock key={asset} asset={asset} title={ASSETS[asset].name} showHorizons />
        ))}
      </div>

      <h2 className="mt-8 text-lg font-semibold">Cách đọc các chỉ số</h2>
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
