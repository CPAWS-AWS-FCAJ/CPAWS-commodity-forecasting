# Hợp đồng dữ liệu API dự báo (MVP)

- Ngày: 2026-10-16 (cập nhật theo review của Long trên PR #6)
- Trạng thái: Đề xuất (chốt cùng ADR-0008 sau buổi họp 16/10)
- Cập nhật 2026-10-25: thêm bản đề xuất `POST /chat` (Phước), chờ Tiến, Tuấn, Khải chốt các mục ở cuối phần đó
- Cập nhật 2026-10-27: nguồn tin cho `get_news` (bảng `NewsLabels`, ADR-0003); `POST /chat` theo prompt và tool v2 (PR #38), tool đọc thẳng bảng `Forecasts` (Khải chốt 26/10), số liệu chi phí và thời gian theo lần chạy dev 26/10; sửa theo review của Tiến và Tuấn trên PR #41 (quyền IAM Bedrock cho global inference profile, hạn chót tính từ `requestTimeEpoch`, vị trí tài nguyên, hai loại `429`); chốt schema 7 trường của `NewsLabels` và cách chọn nguồn tin bằng `NEWS_TABLE_NAME`/`NEWS_DIR`
- Người viết: Khải; góp ý: Long (bản "Chốt target, phân vị và đánh giá mô hình" và "Đánh giá các metric trong metrics.py", 15/10; review PR #6)
- Người dùng: Tuấn (API, Cognito), Tiến (web, Lambda `predict`), Long (DLinear), Phước (tool `get_forecast` của chatbot)

File này là nguồn chuẩn cho định dạng bảng `Forecasts` và JSON trả về. Muốn đổi một trường thì sửa file này qua PR trước, rồi mới sửa code.

## Quy ước chung

| Mục | Giá trị |
|---|---|
| Mã tài sản | `gold`, `silver`, `brent`, `wti` |
| Chuỗi dùng làm target | `gold` → GLD, `silver` → SLV, `brent` → BZ=F, `wti` → CL=F |
| Target | Log return h phiên giao dịch của chuỗi target, h = 1–7; t + h là phiên thứ h sau t theo lịch giao dịch của tài sản (không theo vị trí dòng); NaN khi không có giá hợp lệ tại t hoặc t + h (chi tiết: ADR-0008 mục 1) |
| Mức phân vị lưu và trả về | 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95 (luôn theo thứ tự này, không giảm) |
| Chuẩn hóa phân vị | Một lần duy nhất bằng `normalize_quantiles()` ngay sau khi mô hình xuất kết quả; `prob_up`, giá quy đổi và bản ghi đều dùng bộ phân vị đã chuẩn hóa này (ADR-0008 mục 2) |
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
| `roll_in_horizon` | BOOL | Chỉ dầu: `true` khi có phiên roll (phiên đầu tiên sau một ngày đáo hạn hợp đồng) nằm trong (`base_date`, `target_date` của h = 7], tức ít nhất một return trong kỳ dự báo nối hai hợp đồng. Đáo hạn đúng `base_date` → `true`; đáo hạn đúng `target_date` của h = 7 → `false`. Web hiện dòng lưu ý; vàng, bạc luôn `false` |
| `is_sample` | BOOL | `true` nếu là dữ liệu mẫu để test; web phải hiện nhãn "dữ liệu mẫu" |

Mỗi phần tử của `horizons`:

| Thuộc tính | Kiểu | Ý nghĩa |
|---|---|---|
| `h` | N | 1–7 |
| `target_date` | S | Phiên giao dịch thứ h sau `base_date` theo lịch của tài sản |
| `q` | L of N | 7 log return theo đúng thứ tự `quantile_levels`, đã sắp xếp không giảm |
| `prob_up` | N | Xác suất giá tăng, trong [0.05, 0.95] |
`predict` gọi `normalize_quantiles()` đúng một lần ngay sau khi mô hình xuất kết quả, ghi log số lần phải sắp xếp trước khi sửa (chỉ số "tỷ lệ phân vị cắt nhau"), rồi mới tính `prob_up`, giá và ghi bản ghi. `prob_up()`, `quantiles_to_prices()` và `to_forecast_record()` không tự sửa phân vị: chúng báo lỗi nếu đầu vào không giảm.

Nếu cửa sổ input mới nhất của một tài sản có giá thiếu hoặc bị loại, `predict` không ghi bản ghi mới cho tài sản đó; bản ghi cũ giữ nguyên.

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
      "prices": [69.04, 69.55, 70.46, 71.35, 72.26, 73.18, 73.74],
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

**`GET /accuracy/{asset}`** (tuần 3, Long). Chỉ số tính trên 8 tuần gần nhất, riêng từng h, trên log return. Công thức, mốc 252 phiên và quy tắc dữ liệu hợp lệ nằm ở ADR-0008 mục 4–5; API chỉ trả kết quả:

| Trường | Ý nghĩa | Vai trò |
|---|---|---|
| `pinball_skill` | 1 − PL(mô hình) / PL(mốc 252 phiên); PL = pinball loss trung bình đều trên 7 phân vị | Chỉ số chính |
| `quantile_hit_rates` | Với từng mức τ: tỷ lệ log return thực tế nằm dưới phân vị dự báo q_τ (7 giá trị, so với 0.05…0.95) | Kiểm tra hiệu chỉnh |
| `coverage_80` | Tỷ lệ log return thực tế nằm trong [q10, q90] | Hiển thị trên web |
| `width_80` | Độ rộng trung bình q90 − q10, đơn vị log return | Đi kèm `coverage_80` |
| `interval_score_80` | Interval score của khoảng [q10, q90], α = 0,2 | Kiểm tra hiệu chỉnh |
| `brier_skill` | 1 − BS(mô hình) / BS(tần suất tăng 252 phiên); kèm `brier_skill_vs_half` so với hằng số 0,5 | Xác suất tăng |
| `mae_ratio_vs_naive` | MAE của q50 / MAE của naive (return = 0) trên cùng tập điểm | Báo cáo phụ |
| `sign_accuracy` | Tỷ lệ dự báo đúng chiều, tính trên các điểm có y ≠ 0 và q_0.50 ≠ 0 | Báo cáo phụ |
| `up_rate` | Tỷ lệ log return thực tế dương | Luôn đi cùng `sign_accuracy` |
| `n_obs` | Số điểm hợp lệ thực sự dùng, theo từng chỉ số | |

Mọi chỉ số dùng cùng một quy tắc lọc dữ liệu hợp lệ (ADR-0008 mục 5). Không dùng RMSE, không tính sai số trên mức giá, không gọi tỷ lệ MAE là "MASE". Mốc 252 phiên chỉ dùng các return đã hoàn tất trước thời điểm dự báo.

#### `POST /chat` (tuần 4, Phước)

Trạng thái: **đã duyệt 27/10** (Tiến, Tuấn, Khải). Còn mở: ngày có dữ liệu Fed/EIA (mục 10 ở cuối phần này). Code ở nhánh `feat/chat-api`, mở PR sau khi contract được duyệt.

Hỏi đáp tiếng Việt về dự báo vàng, bạc, Brent, WTI. Lambda nhận câu hỏi, router theo luật chọn nhánh (ADR-0004), gọi Bedrock, trả câu trả lời kèm trích nguồn. Cần header `Authorization` như các endpoint khác; mỗi người dùng có giới hạn lượt hỏi mỗi ngày.

| Nhánh (`branch`) | Model | Tool | `max_tokens` | Prompt |
|---|---|---|---|---|
| `simple` | Nova 2 Lite | Không | 512 | `chatbot-nova-v2` |
| `complex` | Claude Haiku 4.5 | `get_forecast` v2, `get_news`, tối đa 3 vòng | 1500 | `chatbot-haiku-v2` |

- Router không chắc thì chọn `complex`. Router theo luật chưa xong; nếu chưa kịp cho demo 8/11 thì mọi câu đi `complex` (mục 9 ở cuối phần này).
- Prompt v2 đang chờ Khải duyệt bản cuối và khóa SHA-256 ngày 3/11 (`docs/experiments/chatbot-benchmark-v2-proposal.md` mục 10). Lambda dùng đúng bản prompt đã khóa.

**Nguồn dữ liệu của tool `get_forecast` (Khải chốt 26/10)**

- Tool đọc thẳng bảng DynamoDB `Forecasts`, không gọi vòng qua `GET /forecasts/{asset}`: Query theo `asset`, `ScanIndexForward=False`, `Limit=1`, rồi định dạng bằng đúng hàm của Lambda API (`infra/lambda/forecast_api/forecast_format.py`: `latest_record`, `detail_item`). Số trong câu trả lời vì vậy khớp với số trên trang dự báo.
- Sau bước đó, tool chuyển sang dạng rút gọn cho model (`src/chatbot/tools.py`, đặc tả ở `docs/prompts/chatbot-haiku-v2.md`): chỉ q10/q50/q90 theo %, độ rộng khoảng 80% tính sẵn, xác suất tăng theo %; vàng/bạc không có giá. Đây là dữ liệu nội bộ giữa Lambda và model, không phải một phần của API này.
- Lambda chat đóng gói kèm `forecast_format.py` ở gốc asset, và cần quyền `dynamodb:Query` trên bảng `Forecasts`.

**Nguồn dữ liệu của tool `get_news` (chốt schema 27/10 theo review của Tuấn, mục 10)**

Theo ADR-0003, MVP không cần Knowledge Base. Lambda chat đọc tin từ bảng DynamoDB `NewsLabels` hoặc từ file JSON, chọn bằng biến môi trường. Hai nguồn dùng chung schema 7 trường dưới đây. Collector (Tuấn) ghi bảng; Lambda chat chỉ đọc. Code đọc: `src/chatbot/news.py`, chọn nguồn: `infra/lambda/chat_api/handler.py`.

*Khóa của bảng `NewsLabels`*

- Partition key `asset` (S): `gold`, `silver`, `brent` hoặc `wti`.
- Sort key `sk` (S): `<published_at>#<article_id>`, ví dụ `2026-10-13T10:45:00Z#3f9a1c0b7e2d4a61`.
- Một bài liên quan nhiều tài sản thì ghi mỗi tài sản một item, cùng `article_id`.
- `article_id` cố định cho một bài (ví dụ 16 ký tự hex đầu của SHA-256 của `link`), chỉ gồm chữ thường, số và `-`. Collector ghi bằng conditional `PutItem` với `attribute_not_exists(asset) AND attribute_not_exists(sk)` theo RFC #44. Nếu khóa đã tồn tại thì coi là duplicate, không ghi đè item cũ.
- Lambda đọc bằng `Query`: `asset = :asset AND sk BETWEEN "<from_date>" AND "<to_date>T23:59:59Z#~"`, `ScanIndexForward = false`, tối đa 5 trang. So sánh chuỗi chỉ đúng thứ tự thời gian khi `sk` bắt đầu bằng `published_at` đúng định dạng bên dưới.

*7 trường của mỗi tin (bảng và file JSON giống nhau)*

| Trường | Kiểu (DynamoDB / JSON) | Quy tắc |
|---|---|---|
| `title` | S / string | Tiêu đề gốc của bài, tối đa 300 ký tự |
| `summary` | S / string | Tóm tắt 1–3 câu do nhóm hoặc bước gắn nhãn viết, tối đa 600 ký tự. Không chép toàn văn hay đoạn dài của bài (quy tắc tin tức: chỉ lưu tiêu đề, tóm tắt, link, thời gian, nguồn) |
| `link` | S / string | URL bắt đầu bằng `https://` hoặc `http://`. Tin sai điều kiện này bị bỏ, vì chatbot phải trích nguồn có link |
| `source` | S / string | Tên nguồn để hiển thị, ví dụ `Federal Reserve`, `EIA` |
| `published_at` | S / string | ISO 8601 UTC đúng dạng `YYYY-MM-DDTHH:MM:SSZ`: hậu tố `Z`, không có phần lẻ giây, không ghi `+00:00`. Phải trùng phần trước `#` của `sk`. Thời điểm gốc theo múi giờ nguồn (ADR-0003 mục 5) lưu ở thuộc tính khác nếu cần |
| `impact_score` | N / integer | Số nguyên 0–3, theo `docs/prompts/news-labeling-schema.json`. Phải lưu kiểu Number: lưu kiểu String thì tool lỗi khi so sánh với `min_impact` |
| `direction` | S / string | `bullish`, `bearish`, `mixed` hoặc `uncertain` |

- Cả 7 trường đều bắt buộc. Tin thiếu `impact_score` bị coi là 0, nên bị lọc khi `min_impact` ≥ 1.
- Item được có thêm thuộc tính khác, ví dụ `article_id`, `confidence`, `event_type`, `prompt_version`, `model_id`, `fetched_at`, `labeled_at` (ADR-0003 mục 4). Tool bỏ qua chúng và chỉ đưa 7 trường trên cho model.

*Tool trả cho model*

- Mặc định lấy 7 ngày gần nhất tính đến hôm nay (giờ Việt Nam), `min_impact = 2`, khớp prompt `chatbot-haiku-v2`.
- Lọc theo ngày UTC của `published_at` (cùng cách cho cả bảng và file JSON).
- Bỏ tin có `impact_score` < `min_impact` hoặc `link` không hợp lệ. Sắp tin theo `impact_score` giảm dần, cùng mức thì tin mới trước, rồi lấy tối đa 10 tin.
- Lambda chat cần quyền `dynamodb:Query` trên bảng `NewsLabels`.

*Chọn nguồn tin bằng biến môi trường của Lambda chat*

| `NEWS_TABLE_NAME` | `NEWS_DIR` | `get_news` đọc từ |
|---|---|---|
| Có giá trị | Bất kỳ | Bảng DynamoDB có tên đó; `NEWS_DIR` bị bỏ qua |
| Không đặt hoặc rỗng | Có giá trị | File JSON `<NEWS_DIR>/<asset>.json` |
| Không đặt hoặc rỗng | Không đặt hoặc rỗng | Không có nguồn: luôn trả danh sách rỗng, Lambda ghi log cảnh báo |

- **Không tự chuyển nguồn.** Đã đặt `NEWS_TABLE_NAME` mà bảng không có tin trong khoảng ngày thì trả rỗng, không đọc thêm file JSON.
  - Muốn demo bằng JSON: bỏ `NEWS_TABLE_NAME` khỏi cấu hình Lambda và đặt `NEWS_DIR`.
  - Muốn chuyển sang bảng khi collector đã có dữ liệu: đặt `NEWS_TABLE_NAME` (có thể giữ `NEWS_DIR`, vì nó bị bỏ qua).
  - Lambda chọn nguồn một lần khi môi trường chạy khởi tạo. Đổi biến môi trường là cập nhật cấu hình Lambda; các lần gọi sau cập nhật dùng giá trị mới.
- **`NEWS_SORT_KEY`:** tên thuộc tính sort key, mặc định `sk`. Đã chốt `sk` nên không cần đặt.
- **File JSON:**
  - mỗi tài sản một file UTF-8 dạng `{"asset": "wti", "items": [ ... ]}`, mỗi phần tử của `items` theo đúng 7 trường trên; giống định dạng `tests/chatbot/fixtures/news/`;
  - thiếu file của tài sản nào thì tài sản đó không có tin;
  - các file được đóng gói cùng asset Lambda. `NEWS_DIR` là đường dẫn tuyệt đối trong môi trường Lambda, ví dụ `/var/task/news`.
- **Lỗi khi đọc bảng** (sai tên bảng, thiếu quyền, DynamoDB lỗi):
  - `get_news` bắt lỗi và trả cho model `{"error": "news_unavailable", "message": ...}`, kèm log có `request_id`;
  - câu trả lời vẫn có phần dự báo và nói chưa lấy được tin; request không thành `500`.
  - Code hiện chưa làm vậy (lỗi đang lan ra thành `500 internal_error` cho cả request); Phước sửa trong PR code.
- **Demo:** nếu bảng chưa có dữ liệu trước 8/11, dùng bộ nhỏ thông cáo Fed/EIA thật, gắn nhãn tay, đóng gói thành file JSON theo đúng schema trên. Không có nguồn nào thì `get_news` trả rỗng và câu trả lời nói không tìm thấy tin đáng kể.

**Request**

```json
{
  "question": "Dầu WTI phiên tới có khả năng tăng không, vì sao?",
  "context": {"asset": "wti", "page": "product"},
  "history": [
    {"role": "user", "text": "Khoảng dự báo 80% là gì?"},
    {"role": "assistant", "text": "Khoảng dự báo 80% là khoảng từ q10 đến q90..."}
  ]
}
```

| Trường | Bắt buộc | Kiểu | Ràng buộc (đề xuất) |
|---|---|---|---|
| `question` | Có | string | 1–500 ký tự sau khi bỏ khoảng trắng đầu cuối, đếm theo ký tự Unicode (chuẩn hóa NFC), không phải byte |
| `context.asset` | Không | string | `gold`, `silver`, `brent`, `wti`: tài sản của trang người dùng đang xem. Router và model dùng khi câu hỏi không nói tài sản ("nó có tăng không?") |
| `context.page` | Không | string | `home` hoặc `product` |
| `history` | Không | list | Tối đa 6 phần tử (3 lượt hỏi đáp gần nhất), xếp từ cũ đến mới, `role` xen kẽ, bắt đầu bằng `user` và kết thúc bằng `assistant`. Mỗi `text` 1–2000 ký tự |

- Server không lưu hội thoại. Web giữ lịch sử trong bộ nhớ của trang và tự gửi tối đa 6 phần tử gần nhất; quá giới hạn thì server báo lỗi, không tự cắt, để hành vi của web và benchmark giống nhau.
- `history` là dữ liệu do client gửi, có thể bị sửa. Lượt `assistant` trong `history` không phải nguồn số liệu: muốn nêu con số, model vẫn phải gọi `get_forecast` trong lượt hiện tại.
- Cách đưa vào model (Converse `messages`, như code ở `feat/chat-api`):
  - mỗi phần tử `history` thành một lượt `user` hoặc `assistant` theo đúng thứ tự gửi lên;
  - lượt hiện tại là một lượt `user` gồm khối `question`, và khi có `context.asset` thì thêm một khối riêng `[Ngữ cảnh] Người dùng đang xem trang dự báo của: <asset>`. Ngữ cảnh không ghép vào câu hỏi; `context.page` không đưa vào model.
  - Benchmark (Khải) chỉ có câu hỏi một lượt, nên kết quả benchmark chỉ áp dụng cho trường hợp không có `history`.
- Thân request lớn hơn 64 KB bị từ chối.

**Response 200**

```json
{
  "request_id": "0f8e6d2a-5b1c-4c7e-9a3d-2b6f1e4c8a90",
  "answer": "Dự báo WTI ngày cơ sở 14/10/2026, h = 1 (15/10/2026): khoảng dự báo 80% từ 69,54 đến 73,19 USD/bbl, trung vị 71,34 USD/bbl; xác suất tăng 51%. Đây là dữ liệu mẫu, chưa phải dự báo thật.\n\nTin có thể ảnh hưởng: nhóm sản xuất cân nhắc tăng sản lượng (Nguồn: Example Energy Brief, 13/10/2026, https://example.com/news/output-increase).\n\nDự báo mang tính tham khảo, không phải lời khuyên đầu tư.",
  "branch": "complex",
  "prompt_version": "chatbot-haiku-v2",
  "forecasts_used": [
    {"asset": "wti", "base_date": "2026-10-14", "model_version": "sample", "is_sample": true, "stale": false}
  ],
  "citations": [
    {
      "title": "Producer group signals it may raise output next quarter",
      "source": "Example Energy Brief",
      "published_at": "2026-10-13T10:45:00Z",
      "link": "https://example.com/news/output-increase"
    }
  ],
  "truncated": false,
  "blocked": false,
  "quota": {"limit": 20, "used": 3, "remaining": 17, "reset_at": "2026-10-25T17:00:00Z"},
  "disclaimer": "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."
}
```

| Trường | Ý nghĩa |
|---|---|
| `request_id` | ID của lần gọi (lấy từ `requestContext.requestId` của API Gateway), để tra log CloudWatch khi người dùng báo lỗi |
| `answer` | Câu trả lời dạng văn bản thuần, có thể có xuống dòng và gạch đầu dòng `- `. Không phải Markdown hay HTML (xem "Bảo mật") |
| `branch` | `simple` hoặc `complex`: nhánh router đã chọn |
| `prompt_version` | Phiên bản system prompt đã dùng, ví dụ `chatbot-nova-v2`, `chatbot-haiku-v2` |
| `forecasts_used` | Mỗi bản ghi `get_forecast` trả về trong lượt này: `asset`, `base_date`, `model_version`, `is_sample`, `stale` (lấy nguyên từ bản ghi theo `GET /forecasts/{asset}`; `stale = true` khi `stale_sources` không rỗng). Rỗng nếu không gọi tool. Web dùng để hiện nhãn "dữ liệu mẫu" ngay cả khi câu trả lời quên nói |
| `citations` | Tin dùng làm lý do: `title`, `source`, `published_at` (ISO 8601, UTC), `link`. Chỉ gồm tin do `get_news` trả về trong lượt này **và** có `link` xuất hiện trong `answer`. Server không bao giờ lấy link từ chữ model tự viết. Rỗng với nhánh `simple` |
| `truncated` | `true` khi model dừng vì chạm `max_tokens`; web hiện "Câu trả lời bị cắt, hãy hỏi ngắn hơn" |
| `blocked` | `true` khi Guardrails chặn đầu vào hoặc đầu ra; khi đó `answer` là câu chặn cố định, `forecasts_used` và `citations` rỗng. Guardrail còn `DRAFT` nên trước khi publish luôn là `false` |
| `quota` | Lượt hỏi trong ngày của người dùng, tính cả lượt này. `reset_at` là 00:00 giờ Việt Nam của ngày kế tiếp, ghi theo UTC |
| `disclaimer` | Luôn có, đúng chuỗi của các endpoint dự báo |

Câu trả lời có con số dự báo vẫn phải tự nêu khoảng dự báo, xác suất tăng, disclaimer, "dữ liệu mẫu" và "chuỗi đại diện GLD/SLV" theo prompt; các trường `forecasts_used` và `disclaimer` là lớp bảo vệ thứ hai để web hiển thị, không thay thế nội dung câu trả lời.

**Lỗi**

Dạng chung `{"error": "<mã>", "message": "<mô tả>"}`. `message` của lỗi 5xx là câu chung chung, không chứa chi tiết nội bộ.

| HTTP | `error` | Khi nào | Tính lượt? |
|---|---|---|---|
| 400 | `invalid_body` | Thân request không phải JSON, sai kiểu, thiếu `question` hoặc lớn hơn 64 KB | Không |
| 400 | `empty_question` | `question` rỗng sau khi bỏ khoảng trắng | Không |
| 400 | `question_too_long` | `question` dài hơn 500 ký tự | Không |
| 400 | `invalid_context` | `context.asset` hoặc `context.page` không thuộc danh sách | Không |
| 400 | `invalid_history` | `history` quá 6 phần tử, sai thứ tự `role` hoặc có `text` rỗng hay dài hơn 2000 ký tự | Không |
| 429 | `rate_limited` | Đã hết lượt hỏi trong ngày | Không |
| 503 | `model_unavailable` | Bedrock lỗi hoặc bị throttling sau khi đã thử lại. Không tự chuyển câu `complex` sang Nova: nhánh `simple` không có tool nên không trả được số dự báo | Có (đề xuất) |
| 504 | `timeout` | Lambda chạm hạn chót nội bộ trước khi có câu trả lời | Có (đề xuất) |
| 500 | `internal_error` | Lỗi khác | Có (đề xuất) |

Lỗi `rate_limited` có thêm trường `reset_at` và header `Retry-After` (số giây đến `reset_at`):

```json
{"error": "rate_limited", "message": "Bạn đã dùng hết 20 lượt hỏi hôm nay.", "reset_at": "2026-10-25T17:00:00Z"}
```

Một số lỗi do API Gateway tự sinh, không qua Lambda, nên thân lỗi theo mặc định của API Gateway (`{"message": ...}`), không theo dạng chung: `401` (token sai hoặc hết hạn, Cognito authorizer từ chối), `429` khi vượt throttling của stage (hiện 10 request/giây, burst 20), `504` khi quá integration timeout. Cho demo giữ thân lỗi mặc định này (Tiến, Tuấn đồng ý 27/10); `GatewayResponse` 4xx/5xx đã có header CORS nên trình duyệt vẫn đọc được mã lỗi.

Web phân biệt hai loại `429` theo thân lỗi:

- Thân có `"error": "rate_limited"` (hết lượt trong ngày, do Lambda trả): hiện `message` kèm giờ reset quy đổi từ `reset_at` sang giờ Việt Nam.
- Còn lại (throttling của stage, thân mặc định của API Gateway): hiện "Bạn đã hỏi quá nhiều, thử lại sau." như ghi chú trong `web/src/components/ChatPanel.tsx`.

**Giới hạn lượt hỏi theo người dùng (đề xuất)**

- **Mặc định 20 lượt mỗi người mỗi ngày**, đặt bằng biến môi trường của Lambda để đổi không cần sửa code. Căn cứ: lần chạy dev 26/10 (prompt và tool v2) tốn 0,35 USD cho 30 câu Haiku, tức khoảng 0,012 USD mỗi câu `complex` (dữ liệu giả lập, chưa có Guardrails, theo đơn giá tham chiếu ở ADR-0004; lần 23/10 với prompt v1 là 0,297 USD). 20 câu đều là `complex` thì khoảng 0,24 USD/người/ngày.
- **Giới hạn chung toàn hệ thống (đề xuất thêm): 100 lượt mỗi ngày.** User pool tắt tự đăng ký (`self_sign_up_enabled=False`) nên số người dùng có giới hạn, nhưng tổng chi phí vẫn tăng theo số tài khoản. 100 câu `complex` khoảng 1,2 USD/ngày, trường hợp xấu nhất khoảng 36 USD/tháng, vẫn dưới Budgets 50 USD/tháng của cả dự án nhưng chiếm phần lớn; bản 25/10 đề xuất 150 lượt (khoảng 54 USD/tháng nếu dùng hết mỗi ngày, vượt Budgets). Vượt giới hạn chung cũng trả `429 rate_limited`, `message` khác. Giới hạn này cũng đặt bằng biến môi trường của Lambda, riêng với giới hạn theo người dùng.
- **Ngày tính theo giờ Việt Nam (UTC+7)**, reset lúc 00:00.
- **Lượt được tính** khi request đã qua kiểm tra hợp lệ và sắp gọi model, cả nhánh `simple` lẫn `complex`. Lỗi 400 và 429 không tính. Lỗi 5xx sau khi đã tính lượt thì không hoàn lại, để tránh retry liên tục làm tốn tiền Bedrock.
- **Người dùng** xác định bằng claim `sub` của Cognito ID token (`requestContext.authorizer.claims.sub`), không dùng email.

Bộ đếm nằm trong bảng DynamoDB mới `cpaws-<env>-chat-usage` (on-demand, tag theo quy tắc chi phí):

| Thuộc tính | Kiểu | Ý nghĩa |
|---|---|---|
| `pk` | S (partition key) | `user#<sub>`; dòng giới hạn chung là `global` |
| `sk` | S (sort key) | `day#YYYY-MM-DD` theo giờ Việt Nam |
| `request_count` | N | Số lượt đã dùng trong ngày |
| `updated_at` | S | ISO 8601, UTC |
| `expires_at` | N | Thuộc tính TTL: epoch giây, bằng 00:00 giờ Việt Nam của ngày + 3 ngày |

- Mỗi request gọi một `TransactWriteItems` gồm hai `Update` có điều kiện: `ADD request_count :1` trên dòng của người dùng và dòng `global`, kèm điều kiện `attribute_not_exists(request_count) OR request_count < :limit`. Một điều kiện sai thì cả giao dịch bị hủy, nên vượt giới hạn chung không làm mất lượt của người dùng; Lambda trả `429`.
- TTL chỉ để dọn dữ liệu cũ. DynamoDB xóa item hết hạn "trong vòng vài ngày" và item hết hạn chưa xóa vẫn đọc được ([DynamoDB TTL](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html)), nên việc reset theo ngày dựa vào ngày nằm trong `sk`, không dựa vào TTL. Xóa bằng TTL không tốn write capacity.
- Giao dịch thành công không trả về giá trị mới, nên sau đó Lambda đọc lại `request_count` của dòng người dùng bằng `GetItem` với `ConsistentRead = true` để điền `quota.used`.
- Quyền Lambda cần trên bảng này:
  - `dynamodb:UpdateItem`: thao tác `Update` trong `TransactWriteItems` dùng quyền của `UpdateItem`, theo [Using IAM with DynamoDB transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis-iam.html);
  - `dynamodb:GetItem`: đọc lại số lượt đã dùng.
- Bảng không lưu câu hỏi hay câu trả lời.
- Biến môi trường của Lambda chat:
  - `CHAT_USAGE_TABLE_NAME`: bắt buộc; thiếu thì Lambda không khởi động, để không bao giờ chạy mà không có giới hạn;
  - `CHAT_USER_DAILY_LIMIT`: mặc định 20;
  - `CHAT_GLOBAL_DAILY_LIMIT`: mặc định 100.
- Thời gian không đủ cho một lần gọi model ngay từ đầu thì trả `504 timeout` trước khi tính lượt.

**Trả lời một lần hay streaming (Tiến, Tuấn chốt A ngày 27/10)**

Tra tài liệu AWS ngày 25/10/2026:

| | A. REST API hiện có, trả một lần (buffered) | B. REST API, `responseTransferMode = STREAM` | C. Lambda Function URL, `InvokeMode = RESPONSE_STREAM` |
|---|---|---|---|
| Hỗ trợ | Lambda proxy integration như `GET /forecasts` | Có từ 11/2025, chỉ REST API, chỉ `AWS_PROXY`/`HTTP_PROXY` ([1], [2]) | Có ([3], [4]) |
| Đăng nhập | Dùng lại Cognito authorizer | AWS ghi streaming tương thích với authorizer, WAF, throttling ([5]); chưa thử với Cognito authorizer trong tài khoản dự án | Chỉ `AWS_IAM` hoặc `NONE`, không có Cognito authorizer ([6]). `NONE` thì phải tự kiểm tra JWT trong code, sai một chỗ là lộ endpoint gọi Bedrock; `AWS_IAM` thì web cần Cognito Identity Pool để ký SigV4 |
| Timeout | Integration timeout 50 ms – 29 giây; Regional API xin tăng được nhưng có thể phải giảm throttle cấp Region ([7]) | Stream tối đa 15 phút; idle timeout 5 phút (Regional), 30 giây (edge-optimized) ([1]) | Theo timeout của Lambda (tối đa 15 phút) |
| Lambda Python | Giữ Python 3.12 như hiện tại | Lambda chỉ stream sẵn trên runtime Node.js; Python phải dùng custom runtime hoặc Lambda Web Adapter ([3]). Phải xuất đúng định dạng metadata JSON + 8 byte null ([2]) | Cùng giới hạn runtime như B |
| Chi phí | Mỗi câu hỏi 1 request API Gateway + thời gian chạy Lambda + token Bedrock | Như A: streaming tính mỗi 10 MB là 1 request, không phí thêm ([8]); câu trả lời chat luôn dưới 10 MB | Không có phí API Gateway; Lambda và Bedrock như A |
| Rủi ro khác | Người dùng chờ cả câu (benchmark 23/10: Haiku median 6,4 giây, p90 7,8 giây; dev 26/10 với prompt và tool v2: median 5,4 giây, p90 7,7 giây; đều gồm các vòng tool) | Lỗi xảy ra sau khi đã gửi byte đầu không đổi được mã HTTP, phải báo lỗi trong luồng; không dùng được cache, nén, VTL ([1]); Lambda streaming "chưa có ở mọi Region" ([3]), cần kiểm tra `ap-southeast-1` | Mất throttling, log truy cập của API Gateway; thêm một URL và cấu hình CORS riêng |

**Chọn phương án A cho demo 8/11** (Tiến, Tuấn đồng ý 27/10).

- Lý do:
  - giữ nguyên Cognito authorizer, throttling và cách viết Lambda Python đang chạy cho `GET /forecasts`;
  - thời gian trả lời đo được nằm xa dưới mốc 29 giây;
  - B cần đổi runtime hoặc thêm Lambda Web Adapter đúng lúc sát demo;
  - C bỏ mất Cognito authorizer.
- Đánh đổi chấp nhận: không có hiệu ứng chữ chạy. Web hiện trạng thái "Đang trả lời…" trong lúc chờ.
- Hạn chót: trước mỗi lần gọi model, Lambda kiểm tra thời gian còn lại; không đủ thì dừng và trả `504 timeout` theo dạng chung, để tự trả lỗi đúng dạng trước khi API Gateway cắt ở 29 giây.
  - Client Bedrock đặt `connect_timeout` 2 giây, `read_timeout` 15 giây và không tự thử lại (`total_max_attempts = 1`). Mỗi lần gọi vì vậy kéo dài tối đa 17 giây, và Lambda chỉ bắt đầu một lần gọi khi còn ít nhất 17 giây.
  - Lỗi tạm thời của Bedrock (throttling, service unavailable) được Lambda thử lại một lần nếu còn đủ thời gian; `ModelTimeoutException` không thử lại. Hết thời gian chờ Bedrock thì trả `504 timeout`.
  - Câu trả lời rất dài (gần `max_tokens` 1500) có thể vượt 15 giây và thành `504`; câu trả lời 150–250 từ theo prompt thì nằm trong giới hạn này.
  - Hạn chót tính từ lúc API Gateway nhận request: `requestContext.requestTimeEpoch` + 29 giây − 4 giây dự phòng. Đồng thời dừng khi `context.get_remaining_time_in_millis()` còn dưới 3 giây.
  - Đây là ước lượng an toàn. Mốc 29 giây của API Gateway đếm từ lúc gửi request sang Lambda, tức sau Cognito authorizer, nên tính từ `requestTimeEpoch` sớm hơn hạn thật đúng bằng thời gian authorizer chạy. Lambda vì vậy dừng hơi sớm chứ không trễ.
  - Không dùng mốc cố định "25 giây kể từ khi handler chạy" như bản trước. Theo review của Tiến (27/10), mốc đó bỏ sót thời gian khởi động lúc cold start: thời gian này xảy ra trước khi handler chạy nhưng vẫn tính vào 29 giây của API Gateway. Mốc tính từ `requestTimeEpoch` gồm cả thời gian đó. Chỉ dùng `get_remaining_time_in_millis()` thì vẫn bỏ sót, vì nó đo theo timeout của Lambda.
  - Timeout của Lambda đặt 28 giây.
- Bên trong Lambda gọi Converse, không gọi ConverseStream, vì đằng nào cũng trả một lần (ADR-0004 mục 3 cho phép chọn theo luồng xử lý). Nhờ vậy role chỉ cần `bedrock:InvokeModel` (mục "Tài nguyên và quyền IAM" bên dưới).

Nếu sau demo chuyển sang B, giữ nguyên endpoint và JSON ở trên, chỉ thêm chế độ stream khi client gửi `Accept: text/event-stream`:

- lỗi 400 và 429 vẫn trả JSON như trên trước khi stream;
- sau đó server gửi các sự kiện `delta` (đoạn chữ), `done` (mọi trường của response 200 trừ `answer`) hoặc `error`.

Định dạng sự kiện sẽ chốt bằng PR riêng vào file này.

Nguồn (tra 25/10/2026):
- [1] [Stream the integration response for your proxy integrations in API Gateway](https://docs.aws.amazon.com/apigateway/latest/developerguide/response-transfer-mode.html)
- [2] [Set up a Lambda proxy integration with payload response streaming in API Gateway](https://docs.aws.amazon.com/apigateway/latest/developerguide/response-transfer-mode-lambda.html)
- [3] [Response streaming for Lambda functions](https://docs.aws.amazon.com/lambda/latest/dg/configuration-response-streaming.html)
- [4] [Invoking a response streaming enabled function using Lambda function URLs](https://docs.aws.amazon.com/lambda/latest/dg/config-rs-invoke-furls.html)
- [5] [Building responsive APIs with Amazon API Gateway response streaming](https://aws.amazon.com/blogs/compute/building-responsive-apis-with-amazon-api-gateway-response-streaming/) (AWS Compute Blog, 19/11/2025)
- [6] [Select a method to invoke your Lambda function using an HTTP request](https://docs.aws.amazon.com/lambda/latest/dg/furls-http-invoke-decision.html)
- [7] [Quotas for configuring and running a REST API in API Gateway](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-execution-service-limits-table.html)
- [8] [Amazon API Gateway pricing](https://aws.amazon.com/api-gateway/pricing/) (trang giá không ghi đơn giá Singapore; tra bằng AWS Pricing Calculator khi ước tính)

**Tài nguyên và quyền IAM của Lambda chat (theo review của Tiến, Tuấn 27/10)**

- **Lambda `cpaws-<env>-chat-api`** đặt trong `CpawsApiStack`, dùng chung RestApi, Cognito authorizer và throttling với API dự báo; Python 3.12, timeout 28 giây. Lambda dự báo giữ timeout 10 giây, chỉ có quyền đọc và không có quyền Bedrock.
- **Đóng gói:** `infra/lambda/forecast_api/forecast_format.py` và `src/chatbot/tools.py` được chép vào thư mục asset lúc `cdk synth` bằng bundling cục bộ của CDK (không cần Docker). Không chép tay, để mỗi file chỉ có một bản nguồn. Chi tiết chốt ở PR code.
- **Bảng:**
  - `cpaws-<env>-chat-usage` đặt trong `CpawsServing`, cạnh bảng `Forecasts`: on-demand, TTL trên `expires_at`.
  - `NewsLabels` do pipeline tin tạo. Role của Lambda chat dựng ARN từ tên bảng (giống Lambda `predict`), không export chéo stack, để không phụ thuộc thứ tự deploy.
- **Quyền:** mỗi quyền chỉ cấp trên đúng ARN cần dùng, không dùng `*`.

| Quyền | Tài nguyên | Dùng cho |
|---|---|---|
| `dynamodb:UpdateItem`, `dynamodb:GetItem` | Bảng `chat-usage` | Bộ đếm lượt hỏi (giao dịch tăng lượt, rồi đọc lại số lượt đã dùng) |
| `dynamodb:Query` | Bảng `Forecasts` | Tool `get_forecast` |
| `dynamodb:Query` | Bảng `NewsLabels` | Tool `get_news` |
| `bedrock:InvokeModel` | 3 ARN cho mỗi model, xem bên dưới | Converse chỉ cần quyền này ([9]). Không cấp `bedrock:InvokeModelWithResponseStream`; chỉ thêm khi chuyển sang phương án B |
| `bedrock:ApplyGuardrail` | ARN của đúng guardrail đã publish | Chỉ thêm khi Guardrail được publish ([10]) |

Cả hai model đều gọi qua **global** cross-Region inference profile, giống benchmark (`configs/chatbot_benchmark.py`):

| Nhánh | Inference profile ID | `<model>` trong ARN |
|---|---|---|
| `simple` | `global.amazon.nova-2-lite-v1:0` | `amazon.nova-2-lite-v1:0` |
| `complex` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` | `anthropic.claude-haiku-4-5-20251001-v1:0` |

Theo [11], với mỗi model, `bedrock:InvokeModel` phải có đủ 3 statement; thiếu một statement là bị `AccessDenied`:

1. `arn:aws:bedrock:ap-southeast-1:<account>:inference-profile/global.<model>`, điều kiện `aws:RequestedRegion = ap-southeast-1`.
2. `arn:aws:bedrock:ap-southeast-1::foundation-model/<model>`, điều kiện `aws:RequestedRegion = ap-southeast-1` và `bedrock:InferenceProfileArn` = ARN ở dòng 1.
3. `arn:aws:bedrock:::foundation-model/<model>` (ARN không có Region và Account, đúng như tài liệu yêu cầu), điều kiện `aws:RequestedRegion = unspecified` và `bedrock:InferenceProfileArn` = ARN ở dòng 1.

`<account>` lấy từ `Stack.of(self).account` trong CDK, không ghi số Account ID vào repo. Nếu sau này đổi Nova sang gọi bằng model ID trong Region hoặc profile APAC thì phải sửa lại bảng quyền này.

Nguồn bổ sung (tra 27/10/2026):
- [9] [Converse - Amazon Bedrock API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html) ("This operation requires permission for the `bedrock:InvokeModel` action")
- [10] [Set up permissions to use Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-permissions.html)
- [11] [Global cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html), mục "IAM policy requirements for global cross-Region inference"

**Bảo mật**

- **Nội dung tin là dữ liệu không tin cậy.** Tiêu đề và tóm tắt từ `get_news` chỉ được đưa vào model dưới dạng kết quả tool, không ghép vào system prompt. Prompt `chatbot-haiku-v2` có quy tắc bỏ qua chỉ dẫn trong tin, kể cả lặp lại link lạ (benchmark: 0 trên 3 câu injection làm theo); khi Guardrail được publish, bật bộ lọc prompt attack. Câu hỏi và `history` của người dùng cũng là dữ liệu không tin cậy theo cùng quy tắc.
- **Không lộ thông tin nội bộ.** Response và `message` lỗi không chứa: Account ID, ARN, tên bảng, model ID hay inference profile, Guardrail ID, system prompt, stack trace. Chi tiết lỗi chỉ ghi vào CloudWatch kèm `request_id`.
- **Log (đề xuất):** ghi `request_id`, `sub`, `branch`, `prompt_version`, tool đã gọi, token vào/ra, thời gian, `stopReason`. Không ghi email, không ghi nguyên văn câu hỏi và câu trả lời ở `prod`. Log group giữ 1 tháng như Lambda hiện có.
- **Web hiển thị dạng văn bản thuần:**
  - `answer` render như text (React tự escape, giữ xuống dòng bằng CSS), không dùng `dangerouslySetInnerHTML`, không chuyển Markdown sang HTML, không tự biến URL trong `answer` thành link.
  - Link chỉ lấy từ `citations`, chỉ nhận `http`/`https`, mở tab mới với `rel="noopener noreferrer"`. Khớp ghi chú trong `web/src/components/ChatPanel.tsx`.
- **CORS:** `CpawsApiStack` hiện chỉ cho `GET,OPTIONS`; thêm `POST` vào `default_cors_preflight_options.allow_methods` và vào `Access-Control-Allow-Methods` của `GatewayResponse`. Lambda chat tự trả header CORS trong response, như `handler.py` hiện tại.

**Các quyết định** (đã chốt 27/10, trừ phần còn mở ở mục 10)

| # | Quyết định | Đề xuất trong bản này | Người chốt |
|---|---|---|---|
| 1 | Trả một lần hay streaming | A: REST API hiện có, trả một lần; B để sau demo | Tiến, Tuấn |
| 2 | Lambda riêng cho chat hay gộp vào `cpaws-<env>-forecasts-api` | Lambda riêng `cpaws-<env>-chat-api` trong `CpawsApiStack`, timeout 28 giây, hạn chót tính từ `requestTimeEpoch`; Lambda dự báo giữ 10 giây | Tiến |
| 3 | Giới hạn lượt hỏi | 20 lượt/người/ngày theo giờ Việt Nam; giới hạn chung 100 lượt/ngày; lỗi 5xx không hoàn lượt | Tuấn (chi phí), Khải |
| 4 | Bảng `cpaws-<env>-chat-usage`, TTL; quyền IAM của Lambda chat | Bảng chat-usage trong `CpawsServing`. Quyền: `dynamodb:UpdateItem` và `dynamodb:GetItem` trên bảng chat-usage; `dynamodb:Query` trên `Forecasts` và `NewsLabels`; `bedrock:InvokeModel` theo đủ 3 statement global profile cho mỗi model (không cấp `InvokeModelWithResponseStream`); `bedrock:ApplyGuardrail` khi publish. Đóng gói bằng bundling cục bộ của CDK | Tuấn (IAM), Tiến (CDK) |
| 5 | Giới hạn đầu vào và lịch sử hội thoại | `question` 500 ký tự; `history` tối đa 6 phần tử, mỗi phần tử 2000 ký tự, do client gửi | Khải (ảnh hưởng prompt và benchmark), Tiến (web) |
| 6 | Các trường response | `branch`, `prompt_version`, `forecasts_used`, `citations` (chỉ từ `get_news` và có link trong `answer`), `truncated`, `blocked`, `quota` | Khải, Tiến |
| 7 | Chính sách log | Không ghi nguyên văn câu hỏi/câu trả lời ở `prod` | Tuấn |
| 8 | Thân lỗi do API Gateway tự sinh (401, 429 throttling, 504) | Giữ mặc định cho demo; web phân biệt `429 rate_limited` với `429` do throttling theo thân lỗi; thêm `POST` vào CORS | Tuấn, Tiến |
| 9 | Router cho demo 8/11 | Router theo luật nếu kịp; nếu không, mọi câu đi `complex` (đắt hơn, chậm hơn với câu chào hỏi nhưng đúng chính sách). Khải đồng ý phương án dự phòng này (27/10) | Khải, Phước |
| 10 | Nguồn tin cho `get_news` | Đã chốt (27/10): khóa `asset`/`sk`, 7 trường và cách chọn nguồn bằng `NEWS_TABLE_NAME`/`NEWS_DIR` ở mục "Nguồn dữ liệu của tool `get_news`". Còn mở: ngày có dữ liệu Fed/EIA; nếu chưa kịp thì demo bằng file JSON gắn nhãn tay | Tuấn |

## Dữ liệu mẫu

Trước khi DLinear chạy thật, `scripts/seed_forecasts.py` nạp bản ghi mẫu cho 4 tài sản với `is_sample = true` và `model_version = "sample"`. Bản ghi mẫu phải đúng mọi ràng buộc ở trên (7 phân vị không giảm, `prob_up` tính bằng nội suy và kẹp trong [0.05, 0.95]) để web và API được test đúng định dạng. Xóa dữ liệu mẫu trước demo nếu đã có dự báo thật.
