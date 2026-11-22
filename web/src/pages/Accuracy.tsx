import { ASSET_IDS } from "../api/types";
import { GUIDE_ANCHORS, HowToRead } from "../components/HowToRead";
import { ReliabilityBlock } from "../components/ReliabilityBlock";
import { ACCURACY_METRIC_TEXT } from "../lib/accuracy";
import { ASSETS } from "../lib/assets";

// Độ tin cậy rolling_8w của champion hiện hành theo GET /accuracy/{asset} (docs/api/contract.md).
// Chỉ hiện số khi API cho phép (display_status = ready); trạng thái đang thu thập phải hiện đúng.
const METRICS = [ACCURACY_METRIC_TEXT.coverage, ACCURACY_METRIC_TEXT.width, ACCURACY_METRIC_TEXT.sign];

export default function Accuracy() {
  return (
    <div>
      <h1 className="text-2xl font-bold">Độ chính xác</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted">
        Đối chiếu dự báo chạy thật với giá thực tế trong 8 tuần gần nhất, tính trên log return, gộp 7 mức h.
        Không dùng sai số trên mức giá như MAPE.
      </p>
      <HowToRead anchor={GUIDE_ANCHORS.reliability} topic="độ tin cậy 8 tuần" className="mt-2">
        mỗi khối là một sản phẩm. Số chính là tỷ lệ lần giá thực tế nằm trong khoảng 80%; gần 80% là khoảng dự
        báo rộng vừa đúng mức. Khi chưa đủ ngày dự báo đã đối chiếu, khối chỉ hiện tiến độ thu thập.
      </HowToRead>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {ASSET_IDS.map((asset) => (
          <ReliabilityBlock key={asset} asset={asset} title={ASSETS[asset].name} showHorizons explain={false} />
        ))}
      </div>

      <h2 className="mt-8 text-lg font-semibold">Cách đọc các chỉ số</h2>
      <dl className="mt-3 divide-y divide-line rounded-lg border border-line bg-surface">
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
