import { ApiError } from "../api/client";
import { config } from "../api/config";
import { useAccuracy } from "../api/hooks";
import type { AccuracyResponse, AssetId } from "../api/types";
import { formatHorizonCount, reliabilityState } from "../lib/accuracy";
import { formatDate } from "../lib/format";
import { ErrorBlock, LoadingBlock } from "./StateViews";
import { SampleBadge } from "./StatusBadges";

interface Props {
  asset: AssetId;
  /** Tiêu đề khối, ví dụ tên sản phẩm ở trang Độ chính xác. */
  title?: string;
  /** Hiện bảng số đếm X/Y theo từng h (trang Độ chính xác, chế độ nâng cao). */
  showHorizons?: boolean;
}

const UNAVAILABLE = "Tạm thời chưa lấy được độ tin cậy";

/** 503 accuracy_unavailable là lỗi tạm thời của API độ tin cậy, không phải thiếu dữ liệu. */
export function isAccuracyUnavailable(error: unknown): boolean {
  return error instanceof ApiError && error.status === 503 && error.code === "accuracy_unavailable";
}

/** Khối "Độ tin cậy" (rolling_8w) của champion hiện hành: chỉ đọc display_value/display_status. */
export function ReliabilityBlock({ asset, title = "Độ tin cậy 8 tuần gần nhất", showHorizons = false }: Props) {
  const accuracy = useAccuracy(asset);

  return (
    <section aria-label={title} className="rounded-lg border border-line bg-white p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold">{title}</h2>
        {config.useSample ? <SampleBadge /> : null}
      </div>
      <div className="mt-3">
        {accuracy.isPending ? <LoadingBlock label="Đang tải độ tin cậy…" /> : null}
        {accuracy.isError ? (
          isAccuracyUnavailable(accuracy.error) ? (
            <p role="status" className="text-sm text-muted">
              {UNAVAILABLE}
            </p>
          ) : (
            <ErrorBlock message={accuracy.error.message} onRetry={() => void accuracy.refetch()} />
          )
        ) : null}
        {accuracy.data ? <ReliabilityContent data={accuracy.data} showHorizons={showHorizons} /> : null}
      </div>
    </section>
  );
}

function ReliabilityContent({ data, showHorizons }: { data: AccuracyResponse; showHorizons: boolean }) {
  const state = reliabilityState(data);
  const since = data.window.first_eligible_base_date;

  return (
    <div className="space-y-3 text-sm">
      {state.kind === "not_ready" ? <p className="text-muted">Chưa có kết quả đánh giá</p> : null}
      {state.kind === "collecting" ? (
        <p className="text-muted">
          Đang thu thập ({state.baseDates}/{state.minBaseDates})
          <span className="block text-xs">
            Số ngày dự báo đã đối chiếu được với giá thực tế / số ngày tối thiểu để hiện kết quả.
          </span>
        </p>
      ) : null}
      {state.kind === "ready" ? (
        <dl className="grid gap-3 sm:grid-cols-3">
          <Metric
            name="Giá thực tế nằm trong khoảng 80%"
            value={state.coverage}
            hint="Khoảng dự báo 80% đạt yêu cầu khi tỷ lệ này gần 80%."
          />
          <Metric name="Độ rộng khoảng 80% (% giá)" value={state.widthPct} hint="Trung bình q90 − q10, tính theo % giá." />
          <div>
            <dt className="text-muted">Đúng chiều tăng/giảm · tỷ lệ phiên tăng thực tế</dt>
            <dd className="tabular mt-0.5 font-semibold">
              {state.signPair ? `${state.signPair.sign} · ${state.signPair.upRate}` : "—"}
            </dd>
            <dd className="text-xs text-muted">Đọc hai số cùng nhau: đoán luôn “tăng” cũng đúng bằng tỷ lệ phiên tăng.</dd>
          </div>
        </dl>
      ) : null}

      {since ? <p className="text-xs text-muted">Kể từ {formatDate(since)}</p> : null}

      {showHorizons && state.kind !== "not_ready" ? <HorizonCounts data={data} /> : null}
    </div>
  );
}

function Metric({ name, value, hint }: { name: string; value: string | null; hint: string }) {
  return (
    <div>
      <dt className="text-muted">{name}</dt>
      <dd className="tabular mt-0.5 font-semibold">{value ?? "—"}</dd>
      <dd className="text-xs text-muted">{hint}</dd>
    </div>
  );
}

/** Theo từng h chỉ hiện số đếm X/Y (display_status = counts_only), không hiện %. */
function HorizonCounts({ data }: { data: AccuracyResponse }) {
  const hasEmpty = data.by_horizon.some((horizon) => formatHorizonCount(horizon.coverage_80) === null);
  return (
    <div className="overflow-x-auto">
      <table className="tabular w-full text-sm">
        <caption className="text-left text-xs text-muted">
          Số cặp giá thực tế nằm trong khoảng 80% / số cặp đã chấm, theo số phiên h
        </caption>
        <thead>
          <tr className="text-muted">
            <th scope="col" className="px-2 py-1 text-left font-medium">h</th>
            <th scope="col" className="px-2 py-1 text-right font-medium">Trong khoảng 80%</th>
          </tr>
        </thead>
        <tbody>
          {data.by_horizon.map((horizon) => {
            const count = formatHorizonCount(horizon.coverage_80);
            return (
              <tr key={horizon.h} className="border-t border-line">
                <th scope="row" className="px-2 py-1 text-left font-medium">{horizon.h}</th>
                <td className="px-2 py-1 text-right">
                  {count ?? <span title="chưa có cặp đã chấm">—</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {hasEmpty ? <p className="mt-1 text-xs text-muted">— : chưa có cặp đã chấm</p> : null}
    </div>
  );
}
