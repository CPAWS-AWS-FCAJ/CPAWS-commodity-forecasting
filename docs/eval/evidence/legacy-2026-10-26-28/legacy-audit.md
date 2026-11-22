# Bằng chứng legacy `rolling_8w` — base_date 26–28/10/2026 (bản ghi trước cutover PR #48)

- Người lập: Tiến. Thời điểm xuất dữ liệu: 2026-11-02 ~03:15 UTC (10:15 VN). Tài khoản AWS `…1679`, region `ap-southeast-1`, môi trường `dev`.
- Phạm vi: bảng `cpaws-dev-forecasts`, 4 tài sản (gold, silver, brent, wti), `base_date` 26/10, 27/10, 28/10/2026 — 12 bản ghi. Theo contract (#65, §7.3): chính sách `LEGACY_ACCEPT_WITH_EVIDENCE`, chỉ nhận từng record có bằng chứng được duyệt.
- Mốc liên quan: Lambda `cpaws-dev-predict` tạo `2026-10-25T09:15:08Z` (CloudTrail `CreateFunction`, PR #32, `MODEL_VERSION=baseline-q252`); không có `UpdateFunctionConfiguration` từ đó; cutover #48 `2026-10-30T08:10:06Z` (CloudFormation `PredictFunction UPDATE_COMPLETE`, image `ce77bcb`). `issued_at_min` = `2026-10-27T12:00:00Z`. Champion effective base 26/10.

## 1. Bảng đối chiếu từng base_date

| base_date | Lượt predict (UTC, RequestId) | Số lần gọi predict trong giờ đó | `PREDICT_DONE` | `created_at` (cả 4 tài sản) | `model_version` / `is_sample` | Ghi sau đó vào cùng khóa |
|---|---|---|---|---|---|---|
| 2026-10-26 | 2026-10-27 12:15:30Z (`ed5fe050`) | 1 | `snapshot_dt=2026-10-27`, `dry_run=False`, `ok=True`, `written=4`, base 26/10 | `2026-10-27T12:15:31Z` | `baseline-q252` / `false` | Không |
| 2026-10-27 | 2026-10-28 12:16:02Z (`4531bd81`) | 1 | `snapshot_dt=2026-10-28`, `dry_run=False`, `ok=True`, `written=4`, base 27/10 | `2026-10-28T12:16:03Z` | `baseline-q252` / `false` | Không |
| 2026-10-28 | 2026-10-29 12:15:30Z (`36563a5d`) | 1 | `snapshot_dt=2026-10-29`, `dry_run=False`, `ok=True`, `written=4`, base 28/10 | `2026-10-29T12:15:31Z` | `baseline-q252` / `false` | Không (lượt 30/10 08:12Z là `dry_run=True`, `written=0`) |

Cả 4 tài sản cùng `created_at` trong mỗi base_date; không bản ghi nào có `input_snapshot_dt` (đúng với code trước #48).

## 2. Toàn bộ lượt gọi predict 25/10–31/10 (log `START`/`PREDICT_DONE`/`REPORT` + metric `AWS/Lambda Invocations` theo giờ)

| Thời điểm (UTC) | Loại | base_date | Ghi bảng |
|---|---|---|---|
| 25/10 09:21:28Z | Chạy tay kiểm luồng, `dry_run=True` | 23/10 | Không |
| 25/10 09:24:00Z | Chạy tay kiểm luồng | 23/10 | `written=4` |
| 25/10 09:29:09Z | Chạy tay kiểm luồng (ghi lại) | 23/10 | `written=4` |
| 27/10 12:15:30Z | Scheduler | 26/10 | `written=4` |
| 28/10 12:16:02Z | Scheduler | 27/10 | `written=4` |
| 29/10 12:15:30Z | Scheduler | 28/10 | `written=4` |
| 30/10 08:12:33Z | Chạy tay sau deploy #48, `dry_run=True` | 28/10 | Không |
| 30/10 12:15:28Z | Scheduler (hậu cutover) | 29/10 | `written=4`, `already_published=0` |
| 31/10 12:15:44Z | Scheduler (hậu cutover) | 30/10 | `written=4`, `already_published=0` |

Metric `Invocations` của predict khớp: 3 (25/10 09:00–10:00Z), 1 mỗi giờ 12:00Z các ngày 27, 28, 29, 30, 31/10, 1 lúc 30/10 08:00Z; không có giờ nào khác. Ingest có thêm 1 lần gọi 28/10 03:00Z nhưng predict không chạy giờ đó, nên không ghi Forecasts.

## 3. Lập luận không ghi đè / đúng lịch / input-as-of

- **Đúng lịch:** mỗi base 26–28/10 có đúng một lượt predict ghi thật, trong khung Scheduler 12:15 UTC (thứ Ba–thứ Bảy), sau `issued_at_min`.
- **Không ghi đè:** trước #48, mỗi lần ghi thay cả item, kể cả `created_at`. `created_at` của 12 bản ghi trùng giây với lượt Scheduler duy nhất của ngày đó, và sau lượt đó không có lần gọi predict ghi thật nào cho cùng base (lượt 30/10 08:12Z là `dry_run`, không ghi DynamoDB).
- **Model:** `model_version=baseline-q252` trên item và trong `PREDICT_DONE`; biến môi trường không đổi từ 25/10 (CloudTrail).
- **Input-as-of:** `snapshot_dt` = ngày chạy D (ingest 12:15Z cùng ngày); base = phiên cuối trước D; `clean` loại thanh của ngày giao dịch chưa đóng (`incomplete_bar`), nên input chỉ tới base_date. Mốc 252 phiên chỉ dùng return đã hoàn tất trước base.
- **Ngoài phạm vi, đề nghị loại:** base 23/10 (chạy tay, ghi 2 lần, `created_at` < `issued_at_min`), base 16/10 (`is_sample=true`).

## 4. Danh sách đề nghị duyệt (12 record)

| # | asset | base_date | model_version | created_at |
|---|---|---|---|---|
| 1 | gold | 2026-10-26 | baseline-q252 | 2026-10-27T12:15:31Z |
| 2 | silver | 2026-10-26 | baseline-q252 | 2026-10-27T12:15:31Z |
| 3 | brent | 2026-10-26 | baseline-q252 | 2026-10-27T12:15:31Z |
| 4 | wti | 2026-10-26 | baseline-q252 | 2026-10-27T12:15:31Z |
| 5 | gold | 2026-10-27 | baseline-q252 | 2026-10-28T12:16:03Z |
| 6 | silver | 2026-10-27 | baseline-q252 | 2026-10-28T12:16:03Z |
| 7 | brent | 2026-10-27 | baseline-q252 | 2026-10-28T12:16:03Z |
| 8 | wti | 2026-10-27 | baseline-q252 | 2026-10-28T12:16:03Z |
| 9 | gold | 2026-10-28 | baseline-q252 | 2026-10-29T12:15:31Z |
| 10 | silver | 2026-10-28 | baseline-q252 | 2026-10-29T12:15:31Z |
| 11 | brent | 2026-10-28 | baseline-q252 | 2026-10-29T12:15:31Z |
| 12 | wti | 2026-10-28 | baseline-q252 | 2026-10-29T12:15:31Z |

## 5. File gốc (SHA-256)

| File | Nguồn | SHA-256 |
|---|---|---|
| `forecasts-gold.json` | `dynamodb query`, base 20–31/10 | `c150a67e950e3027837f71b1028ea54c363617090027cb85c6eb64fccb715dbe` |
| `forecasts-silver.json` | như trên | `8db0170590cd718574b6d699f36559218c4ec365c87e5e6118a5c646921a8b2d` |
| `forecasts-brent.json` | như trên | `087075588af96829bb7cd6a6e819a0d806e31c4d2265d1a502112f1e875a7137` |
| `forecasts-wti.json` | như trên | `d3fc7babb923c87ef34ed73b20a83d053930f7d600f2c8f10a0335c8c433017a` |
| `invocations-predict-hourly.json` | `cloudwatch get-metric-statistics`, 25/10–2/11, period 3600 | `97bc3b484b2255c3716cea0f93085d93769e8aeee77721e5241cf9694fee1ff9` |
| `invocations-ingest-hourly.json` | như trên | `e3f053560c2f8597eec45e4a7a059a81466786349afc58776fe2e248f433e957` |
| `predict-logs-2510-3110.json` | `logs filter-log-events` `?START ?PREDICT_DONE ?PREDICT_ALREADY_PUBLISHED ?REPORT`, 25/10 00:00Z–1/11 00:00Z; **đã lọc trường `last_price`** (xem dưới) | `33b1dd25f4beaae207ce5597918b86decf22eabed2a856a4233d9edb11d81eaa` |

File nằm cùng thư mục với tài liệu này. Bản gốc PowerShell xuất (UTF-8 có BOM, CRLF) đã được chuẩn hóa sang UTF-8 không BOM, LF theo `.gitattributes`; nội dung JSON không đổi (đã so `json.loads`). SHA-256 ở trên tính trên file trong repo. Repo public và quy tắc nhóm không commit dữ liệu giá (ADR-0005), nên trong `predict-logs-2510-3110.json` đã bỏ trường `last_price` khỏi 9 dòng `PREDICT_DONE` (36 giá trị, 4 tài sản); mọi trường khác (`snapshot_dt`, `model_version`, `dry_run`, `ok`, `written`, `already_published`, `base_date`, `n_crossed`, `prob_up`, `written_to`) và các dòng `START`/`REPORT` giữ nguyên. Bản xuất gốc đầy đủ do Tiến giữ ngoài repo. Log Lambda chỉ giữ 30 ngày (log 27/10 hết khoảng 26/11), nên các file này là bản lưu bằng chứng.
