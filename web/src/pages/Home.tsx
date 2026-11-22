import { Link } from "react-router-dom";
import { useForecasts } from "../api/hooks";
import { AssetCard, rangeScale } from "../components/AssetCard";
import { SourceNote } from "../components/SourceNote";
import { ErrorBlock } from "../components/StateViews";
import { isPriceHidden } from "../lib/assets";
import { METAL_PRICE_NOTE } from "../lib/source";
import { isMetal } from "../lib/units";

/** Khung chờ cùng hình dạng lưới thẻ (không nhấp nháy). */
function CardsSkeleton() {
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">Đang tải dự báo…</span>
      <ul aria-hidden="true" className="grid gap-4 md:grid-cols-2">
        {[0, 1, 2, 3].map((key) => (
          <li key={key} className="h-72 rounded-lg border border-line bg-surface p-6">
            <div className="h-5 w-32 rounded bg-surface-muted" />
            <div className="mt-6 h-8 w-40 rounded bg-surface-muted" />
            <div className="mt-10 h-px w-full bg-line" />
            <div className="mt-6 h-4 w-3/4 rounded bg-surface-muted" />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Trang chủ khi đã đăng nhập: 4 thẻ dự báo 7 phiên, cùng một thang cho thanh khoảng. */
export default function Home() {
  const { data, isPending, isError, error, refetch } = useForecasts();
  const items = data?.items ?? [];
  const scale = items.length ? rangeScale(items) : undefined;
  const metalPricesShown = items.some((item) => isMetal(item.asset) && !isPriceHidden(item.asset));

  return (
    <div>
      <header className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Dự báo giá vàng, bạc và dầu</h1>
        <p className="mt-2 text-sm text-muted sm:text-base">
          Khoảng giá nhiều khả năng và xác suất tăng sau 7 phiên giao dịch. Mở từng sản phẩm để xem
          từng phiên 1–7 và hỏi chatbot vì sao.
        </p>
      </header>

      <div className="mt-8">
        {isPending ? <CardsSkeleton /> : null}
        {isError ? <ErrorBlock message={error.message} onRetry={() => void refetch()} /> : null}
        {data && items.length === 0 ? <p className="text-sm text-muted">Chưa có dự báo nào.</p> : null}
        {items.length > 0 ? (
          <>
            <ul className="grid gap-4 md:grid-cols-2">
              {items.map((item) => (
                <li key={item.asset} className="h-full">
                  <AssetCard item={item} hidePrice={isPriceHidden(item.asset)} scale={scale} />
                </li>
              ))}
            </ul>
            <div className="mt-6 flex flex-col gap-4 text-xs text-muted md:flex-row md:items-start md:justify-between">
              <div className="max-w-2xl space-y-1.5">
                <p>
                  Thanh dưới mỗi thẻ: dải màu là khoảng 80% sau 7 phiên, vạch đậm ở giữa là giá cuối, vạch
                  xanh là trung vị. Bốn thẻ dùng chung một thang % để so độ rộng khoảng.
                </p>
                {metalPricesShown ? <p>{METAL_PRICE_NOTE}</p> : null}
                <SourceNote />
              </div>
              <Link
                to="/guide"
                className="shrink-0 text-sm font-medium text-forecast underline-offset-4 hover:underline"
              >
                Cách đọc dự báo
              </Link>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
