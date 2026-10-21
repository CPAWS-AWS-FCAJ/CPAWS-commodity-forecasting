import { useForecasts } from "../api/hooks";
import { AssetCard } from "../components/AssetCard";
import { ErrorBlock, LoadingBlock } from "../components/StateViews";

export default function Home() {
  const { data, isPending, isError, error, refetch } = useForecasts();

  return (
    <div>
      <h1 className="text-2xl font-bold">Dự báo giá vàng, bạc và dầu</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted">
        Khoảng giá nhiều khả năng và xác suất tăng trong 1–7 ngày tới. Mô hình dự báo log return rồi quy
        đổi sang khoảng giá, nên luôn có khoảng và xác suất đi kèm, không chỉ một con số.
      </p>

      <div className="mt-6">
        {isPending ? <LoadingBlock label="Đang tải dự báo…" /> : null}
        {isError ? <ErrorBlock message={error.message} onRetry={() => void refetch()} /> : null}
        {data ? (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {data.items.map((item) => (
              <li key={item.asset} className="h-full">
                <AssetCard item={item} />
              </li>
            ))}
          </ul>
        ) : null}
        {data && data.items.length === 0 ? (
          <p className="text-sm text-muted">Chưa có dự báo nào.</p>
        ) : null}
      </div>
    </div>
  );
}
