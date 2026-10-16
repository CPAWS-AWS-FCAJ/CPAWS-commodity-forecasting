# Hợp đồng dữ liệu API dự báo (MVP)

- Ngày: 2026-10-16
- Trạng thái: Đề xuất
- Người viết: Khải; góp ý: Long (bản "Chốt target, phân vị và đánh giá mô hình" và "Đánh giá các metric trong metrics.py", 15/10)
- Người dùng: Tuấn (API, Cognito), Tiến (web, Lambda `predict`), Long (DLinear), Phước (tool `get_forecast` của chatbot)

File này là nguồn chuẩn cho định dạng bảng `Forecasts` và JSON trả về. Muốn đổi một trường thì sửa file này qua PR trước, rồi mới sửa code.

## Quy ước chung

| Mục | Giá trị |
|---|---|
| Mã tài sản | `gold`, `silver`, `brent`, `wti` |
| Chuỗi dùng làm target | `gold` → GLD, `silver` → SLV, `brent` → BZ=F, `wti` → CL=F |
| Target | Log return h phiên giao dịch của chuỗi target, h = 1–7; giá ≤ 0 cho NaN |
| Mức phân vị lưu và trả về | 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95 (luôn theo thứ tự này, không giảm) |
| Phân vị web hiển thị | 0.10, 0.50, 0.90 (khoảng danh nghĩa 80%) |
| Xác suất tăng | Nội suy tuyến tính giữa các phân vị, kẹp trong [0.05, 0.95]; là phép xấp xỉ, chưa hiệu chỉnh |
| `base_date` | Ngày có giá cuối cùng của tài sản (không phải ngày chạy), `YYYY-MM-DD` |
| Thời gian | `created_at` theo ISO 8601, UTC |
| Đơn vị giá hiển thị | Vàng, bạc: `USD/oz`; Brent, WTI: `USD/bbl` |
| Quy đổi giá | `price_q = last_price × exp(return_q)`; quy đổi VND làm ở web theo skill `forecast-display` |

Vàng và bạc: mô hình dự báo return của quỹ GLD, SLV (chuỗi đại diện cho kim loại). `last_price` là giá hiển thị theo USD/oz, quy đổi từ GLD/SLV theo ADR-0005. Web và chatbot phải nói rõ con số là dự báo dựa trên chuỗi đại diện, không phải giá giao ngay.

## Bảng DynamoDB `Forecasts`

- Partition key: `asset` (String)
- Sort key: `base_date` (String, `YYYY-MM-DD`)
- Bản ghi mới nhất của một tài sản: `Query` theo `asset`, `ScanIndexForward=false`, `Limit=1`
- Số lưu dạng Number (Decimal), làm tròn 6 chữ số thập phân

| Thuộc tính | Kiểu | Ý nghĩa |
|---|---|---|
| `asset` | S | Mã tài sản |
| `base_date` | S | Ngày dữ liệu cuối |
| `created_at` | S | Thời điểm `predict` ghi bản ghi |
| `model_version` | S | Ví dụ `dlinear-2026-10-20`; `sample` cho dữ liệu mẫu |
| `target_series` | S | `GLD`, `SLV`, `BZ=F` hoặc `CL=F` |
| `last_price` | N | Giá tại `base_date`, theo đơn vị hiển thị |
| `price_unit` | S | `USD/oz` hoặc `USD/bbl` |
| `quantile_levels` | L of N | `[0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]` |
| `horizons` | L of M | 7 phần tử, h = 1–7 (cấu trúc bên dưới) |
| `fx_usd_vnd` | N | Tỷ giá USD/VND dùng để hiển thị |
| `fx_date` | S | Ngày của tỷ giá |
| `stale_sources` | L of S | Nguồn bị lỗi lần chạy này (lấy từ `quality.json`); rỗng nếu không có |
| `roll_in_horizon` | BOOL | Chỉ dầu: kỳ dự báo chứa ngày đáo hạn hợp đồng (web hiện dòng lưu ý); vàng, bạc luôn `false` |
| `is_sample` | BOOL | `true` nếu là dữ liệu mẫu để test; web phải hiện nhãn "dữ liệu mẫu" |

Mỗi phần tử của `horizons`:

| Thuộc tính | Kiểu | Ý nghĩa |
|---|---|---|
| `h` | N | 1–7 |
| `target_date` | S | Phiên giao dịch thứ h sau `base_date` theo lịch của tài sản |
| `q` | L of N | 7 log return theo đúng thứ tự `quantile_levels`, đã sắp xếp không giảm |
| `prob_up` | N | Xác suất giá tăng, trong [0.05, 0.95] |

`predict` phải sắp xếp lại các phân vị trước khi ghi nếu mô hình trả ra phân vị cắt nhau, và ghi log số lần phải sắp xếp (dùng cho chỉ số "tỷ lệ phân vị cắt nhau").

## Endpoint

Mọi endpoint trừ `/health` cần header `Authorization: <Cognito ID token>`. Lỗi trả về dạng `{"error": "<mã>", "message": "<mô tả>"}`.

### `GET /health`

Không cần đăng nhập.

```json
{"status": "ok"}
```

### `GET /forecasts`

Tóm tắt dự báo mới nhất của cả 4 tài sản cho trang chủ.

```json
{
  "items": [
    {
      "asset": "gold",
      "target_series": "GLD",
      "base_date": "2026-10-14",
      "last_price": 2655.4,
      "price_unit": "USD/oz",
      "h1": {"target_date": "2026-10-15", "p10": 2621.7, "p50": 2657.1, "p90": 2690.2, "prob_up": 0.53},
      "h7": {"target_date": "2026-10-23", "p10": 2571.9, "p50": 2662.3, "p90": 2748.8, "prob_up": 0.55},
      "stale": false,
      "roll_in_horizon": false,
      "is_sample": true
    }
  ],
  "disclaimer": "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."
}
```

`p10`, `p50`, `p90` là giá đã quy đổi; `stale = true` khi `stale_sources` không rỗng.

### `GET /forecasts/{asset}`

Dự báo mới nhất của một tài sản, đủ 7 mức h và 7 phân vị (dùng cho trang sản phẩm, chế độ nâng cao và tool chatbot). Tham số tùy chọn `?date=YYYY-MM-DD` để lấy bản ghi có `base_date` đó.

```json
{
  "asset": "wti",
  "target_series": "CL=F",
  "base_date": "2026-10-14",
  "created_at": "2026-10-15T12:40:05Z",
  "model_version": "sample",
  "last_price": 71.32,
  "price_unit": "USD/bbl",
  "quantile_levels": [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95],
  "horizons": [
    {
      "h": 1,
      "target_date": "2026-10-15",
      "returns": [-0.0325, -0.0251, -0.0122, 0.0004, 0.0131, 0.0258, 0.0334],
      "prices": [69.04, 69.55, 70.45, 71.35, 72.26, 73.18, 73.74],
      "prob_up": 0.51
    }
  ],
  "fx": {"usd_vnd": 26310, "date": "2026-10-14"},
  "stale_sources": [],
  "roll_in_horizon": false,
  "is_sample": true,
  "disclaimer": "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."
}
```

Lỗi: `400 invalid_asset` (mã tài sản sai), `400 invalid_date`, `404 not_found` (chưa có bản ghi).

### Thêm sau

**`GET /accuracy/{asset}`** (tuần 3, Long). Chỉ số tính trên 8 tuần gần nhất, riêng từng h, theo bộ chỉ số trong bản đánh giá của Long:

| Trường | Ý nghĩa | Vai trò |
|---|---|---|
| `pinball_skill` | 1 − pinball(mô hình) / pinball(mốc 252 phiên) | Chỉ số chính |
| `quantile_hit_rates` | Tỷ lệ giá thực tế nằm dưới từng phân vị (7 giá trị, so với 0.05…0.95) | Kiểm tra hiệu chỉnh |
| `coverage_80`, `width_80` | Độ phủ và độ rộng trung bình của khoảng [q10, q90] | Hiển thị trên web |
| `interval_score_80` | Interval score của khoảng 80% | Kiểm tra hiệu chỉnh |
| `brier_skill` | Brier skill score của `prob_up` so với tần suất tăng 252 phiên | Xác suất tăng |
| `mae_ratio_vs_naive` | MAE của q50 / MAE của naive (return = 0) trên cùng giai đoạn | Báo cáo phụ |
| `sign_accuracy`, `up_rate` | Tỷ lệ đúng chiều, luôn đi cùng tỷ lệ tăng thực tế | Báo cáo phụ |
| `n_obs` | Số điểm dùng để tính | |

Không dùng RMSE, không tính sai số trên mức giá, không gọi tỷ lệ MAE là "MASE". Mốc 252 phiên chỉ dùng các return đã hoàn tất trước thời điểm dự báo.

**`POST /chat`** (tuần 4, Phước): hỏi đáp; giới hạn lượt hỏi theo người dùng mỗi ngày.

## Dữ liệu mẫu

Trước khi DLinear chạy thật, `scripts/seed_forecasts.py` nạp bản ghi mẫu cho 4 tài sản với `is_sample = true` và `model_version = "sample"`. Bản ghi mẫu phải đúng mọi ràng buộc ở trên (7 phân vị không giảm, `prob_up` tính bằng nội suy và kẹp trong [0.05, 0.95]) để web và API được test đúng định dạng. Xóa dữ liệu mẫu trước demo nếu đã có dự báo thật.
