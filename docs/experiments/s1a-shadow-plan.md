# S1a chạy song song (shadow) trong Lambda predict: kế hoạch (chốt trước khi viết code)

- Ngày: 28/10/2026
- Người viết: Khải (bản nháp do Claude soạn); người review: Tiến (predict, CDK), Tuấn (IAM), Long (dữ liệu cho `rolling_8w`)
- Trạng thái: **Chốt trước khi viết code.** Commit file này trước PR code. Thay đổi sau đó ghi thành mục mới có ngày và lý do.
- Căn cứ: ADR-0010 (S1a là challenger), ADR-0011 (chấm champion/challenger hằng tuần thay cho retrain), ADR-0008 (target, phân vị, `normalize_quantiles()` đúng một lần), RFC #45 (`rolling_8w`).

## 0. Không có lần nhìn mới vào validation 2019

Kế hoạch này không chọn hay chỉnh tham số. S1a giữ đúng định nghĩa đã chốt trong `docs/experiments/k3b-volatility-plan.md` và `configs/k3b.py`. Test chỉ kiểm S1a trong Lambda ra **giống từng bit** bản đã đánh giá ở K3b, trên dữ liệu giả, không tính chỉ số nào. Tập test 2020 → nay vẫn không chạy.

## 1. Mục tiêu

Mỗi ngày, cùng lần chạy với champion `baseline-q252`, Lambda predict tính thêm dự báo S1a cho 4 tài sản và lưu lên S3. Job `rolling_8w` dùng các bản này để chấm champion và S1a trên cùng các cặp dự báo–thực tế.

S1a không hiển thị cho người dùng, không ghi DynamoDB `Forecasts`, không đổi `contract.md`.

## 2. S1a là gì (chốt, không đổi)

- Champion `baseline-q252` cho ra phân vị mốc Q[h, τ] tại ngày gốc t.
- k_t = clip(σ_short,t / σ_long,t, 0,5, 2,0), với:
  - r_s = ln(P_s / P_{s−1}) cho cặp phiên liền kề theo lịch tài sản; cặp vắt qua phiên thiếu, bị loại hoặc giá ≤ 0 là NaN;
  - σ_long,t: độ lệch chuẩn mẫu (ddof 1) các r_s hợp lệ trong 252 phiên gần nhất ≤ t, cần ≥ 200 return hợp lệ;
  - σ_short,t: EWMA với λ = 0,94, khởi tạo tại return hợp lệ thứ 252 của chuỗi bằng phương sai mẫu của 252 return đầu; r_t không hợp lệ thì giữ σ² cũ.
- S1a: q[h, τ] = Q[h, τ] + (k_t − 1)·(Q[h, τ] − Q[h, 0,5]). Trung vị giữ nguyên, nên `mae_ratio_vs_naive` và `sign_accuracy` giống champion; khác biệt chỉ nằm ở độ rộng khoảng.
- `model_version`: `s1a-l094`.

## 3. Vị trí trong code

### 3.1. Module mới không phụ thuộc PyEMD

`src/forecast/vol_scaled.py` import `src.features.ceemdan_cache` → `src.forecast.decomposition` → PyEMD. Image predict không có PyEMD và không chép `configs/`.

- Tách phần thuần NumPy/pandas sang `src/forecast/vol_scale_core.py`: `daily_log_returns`, `long_vol`, `ewma_vol`, `scale_quantiles`, và hàm mới `k_at(prices, asset, base_date, invalid_dates) -> (k, sigma_short, sigma_long)`.
- Hằng số (λ 0,94, kẹp [0,5; 2,0], cửa sổ 252, tối thiểu 200, khởi tạo 252) khai báo trong module này. Test kiểm chúng bằng đúng `configs/k3b.py`.
- `vol_scaled.py` import lại các hàm từ `vol_scale_core.py`, nên K3b vẫn tái lập như cũ.
- `test_predict_requirements_cover_runtime_imports` phải tiếp tục xanh.

### 3.2. Trong `predict_asset`

1. Champion chạy như hiện tại: kiểm `base_date`, cửa sổ, `publication_as_of`, rồi `raw = model.predict(...)`.
2. **Chỉ khi champion ok**, nhánh shadow dùng chính `raw` của champion (trước `normalize_quantiles()`), cùng `base_date`, cùng snapshot cắt tới `base_date`, cùng danh sách ngày bị loại (`rejected`).
3. `k_t = k_at(...)` trên toàn bộ chuỗi giá của snapshot ≤ `base_date`. Nếu k_t không hợp lệ (NaN) thì bỏ S1a cho tài sản đó, log `PREDICT_SHADOW_SKIPPED asset=… reason=invalid_k`.
4. `q_s1a = scale_quantiles(raw, [k_t])`, rồi `normalize_quantiles()` đúng một lần cho S1a.
5. Dựng bản ghi bằng `to_forecast_record(..., model_version="s1a-l094", is_sample=False, created_at=<cùng created_at của champion>)`, thêm khóa `shadow`: `{"k": …, "sigma_short": …, "sigma_long": …, "champion_model_version": "baseline-q252"}`.
6. `AssetResult` thêm `shadow_record`; `run_predict` ghi bản ghi champion như cũ, rồi ghi shadow qua `ShadowSink`.

## 4. Đầu ra trên S3

- Key: `eval/shadow/s1a-l094/dt=<ngày chạy UTC>/<asset>.json`. `dt` theo cùng quy ước với `clean/prices/dt=<ngày>/`.
- Nội dung: đúng cấu trúc bản ghi `Forecasts` cộng khóa `shadow`. Job `rolling_8w` đọc champion và S1a bằng cùng một hàm.
- **Không ghi đè**, cùng tinh thần D04: `put_object(..., IfNoneMatch="*")`. Nếu object đã có (HTTP 412 `PreconditionFailed`), log WARNING `PREDICT_SHADOW_ALREADY_PUBLISHED asset=… dt=…` và tính là xong. `S3Storage.write_bytes` thêm tham số `if_none_match: bool = False`; mặc định giữ hành vi cũ cho ingest.
- Chạy `--dest local`: ghi `data/lake/eval/shadow/...`, được ghi đè (chỉ để xem thử).
- Ước tính: 4 object, mỗi object dưới 5 KB mỗi ngày; chi phí S3 gần 0.

## 5. Cô lập lỗi

- Toàn bộ nhánh shadow của một tài sản nằm trong `try/except Exception`. Lỗi chỉ log ERROR `PREDICT_SHADOW_FAILED asset=… error=<loại lỗi>` kèm traceback.
- Kết quả champion (`status`, `ok`, `written`) không đổi khi shadow lỗi. Lambda không raise vì shadow, alarm `cpaws-dev-predict-errors` không bật.
- `PREDICT_DONE` thêm `shadow: {"model_version": "s1a-l094", "written": n, "already_published": n, "skipped": n, "failed": n}`.
- Không thêm alarm cho shadow ở MVP. Khải kiểm `shadow.failed` trong log mỗi tối cùng lúc kiểm lần chạy.

## 6. Bật, tắt và rollback

- Biến môi trường `SHADOW_MODELS`, danh sách cách nhau bằng dấu phẩy. Rỗng hoặc không đặt thì tắt; giá trị chấp nhận duy nhất là `s1a-l094`.
- CDK đặt `SHADOW_MODELS=s1a-l094` cho Lambda predict.
- Rollback: đặt lại biến rỗng rồi deploy `CpawsData`, không cần build image.

## 7. Thời gian chạy

- Thêm cho mỗi tài sản: 1 lần đọc chuỗi giá đã có trong bộ nhớ, 2 phép rolling trên khoảng 3.700 phiên, 1 vòng EWMA, 1 phép nhân mảng 7 × 7. Ước tính dưới 0,5 giây cho cả 4 tài sản.
- Log `PREDICT_SHADOW_MS asset=… ms=…`.
- Tiêu chí chấp nhận: `Duration` tối đa của 3 lần chạy đầu sau deploy tăng dưới 2 giây so với 3 lần chạy liền trước; timeout 120 giây và bộ nhớ 1024 MB giữ nguyên. Vượt ngưỡng thì tắt bằng `SHADOW_MODELS` và xem lại.

## 8. IAM và CDK

- **Tuấn:** thêm vào role Lambda predict trong `CpawsData` một statement `s3:PutObject` trên `arn:aws:s3:::cpaws-dev-lake/eval/shadow/*`. Không cần `GetObject`, `ListBucket` hay `DeleteObject`; ghi có điều kiện `IfNoneMatch` vẫn chỉ cần `s3:PutObject`.
- **Tiến:** thêm biến `SHADOW_MODELS`, build image predict mới, deploy `CpawsData` với đủ context đang dùng (`ingest_image_tag`, `predict_image_tag`, `eia_parameter_name`). Ngoài khung 19:05–19:35.
- Không thêm tài nguyên AWS mới.

## 9. Chống rò rỉ dữ liệu tương lai

- k_t chỉ dùng r_s với s ≤ `base_date`. Snapshot đã được cắt tới `base_date` và đi qua cùng kiểm tra `publication_as_of` với champion.
- Không đọc giá sau `base_date`, không đọc dữ liệu 2020 → nay ngoài những gì champion đã đọc.

## 10. Test (thêm vào `tests/`)

1. `vol_scale_core` cho kết quả **giống từng bit** `vol_scaled.vol_ratio` và `s1_quantiles` của K3b trên dữ liệu giá giả, ở nhiều ngày gốc.
2. Hằng số trong `vol_scale_core` bằng `configs/k3b.py` (`S1_LAMBDA["S1a"]`, `K_CLIP`, `SIGMA_LONG_WINDOW`, `SIGMA_MIN_OBS`, `EWMA_INIT_OBS`).
3. Shadow S1a từ đầu ra champion của Lambda (`Quantile252Model` trên cửa sổ `make_windows`) bằng `s1_quantiles` của K3b tại cùng ngày gốc (sai lệch ≤ 1e-12). Nếu hai bên lệch (ví dụ do cửa sổ có phiên bị loại), **dừng và báo lại**, không nới sai số.
4. k_t tại t không đổi khi nối thêm giá sau t.
5. Trung vị S1a bằng trung vị champion từng bit; phân vị không đảo thứ tự.
6. Nhánh shadow lỗi (giả lập exception) → champion vẫn ghi, `ok=True`, `shadow.failed=1`, có log `PREDICT_SHADOW_FAILED`.
7. k_t NaN (ít hơn 200 return hợp lệ) → `shadow.skipped=1`, champion không bị ảnh hưởng.
8. Ghi S3 lần hai cùng key (moto) → `already_published`, object giữ nguyên.
9. `SHADOW_MODELS` rỗng → không tính, không ghi S3; giá trị lạ → lỗi cấu hình rõ ràng khi khởi động.
10. `vol_scaled.py` (K3b) vẫn chạy và các test K3b cũ vẫn xanh.

## 11. Dùng kết quả

- Job `rolling_8w` đọc champion từ DynamoDB và S1a từ `eval/shadow/s1a-l094/`, chỉ chấm trên các cặp có **cả hai** mô hình (cùng `asset`, `base_date`, `h`).
- Dữ liệu S1a bắt đầu từ lần chạy sau khi deploy, nên so sánh tính từ ngày đó, không từ 27/10. Báo cáo ghi rõ ngày bắt đầu.
- Kết quả chỉ để báo cáo và cho buổi bảo vệ. Đổi champion vẫn theo ADR-0008 và ADR-0009 mục 4, phải có ADR; không tự động.

## 12. Lịch

| Ngày | Việc | Người |
|---|---|---|
| 29/10 | Commit kế hoạch này | Khải |
| 2–3/11 | PR code (module core, nhánh shadow, `ShadowSink`, test) | Khải; Tiến review |
| 2–3/11 | PR CDK: quyền `eval/shadow/*`, biến `SHADOW_MODELS` | Tiến viết, Tuấn review IAM |
| ≤ 6/11 | Build image predict, deploy `CpawsData`; kiểm `Duration` và 4 object đầu tiên trên S3 | Tiến, Khải |

Nếu PR chống ghi đè dự báo được merge trước, gộp vào cùng một lần build image predict.

## 13. Ngoài phạm vi

- Hiển thị S1a trên web hoặc chatbot.
- Ghi S1a vào DynamoDB.
- S1b, S2, K3 hay bất kỳ ứng viên nào khác chạy song song.
- Tự động đổi champion.

## 14. Cập nhật 28/10 theo review của Long trên #49 (trước khi viết code)

1. **Trường dữ liệu và bằng chứng phát hành.**
   - File shadow giữ nguyên bản ghi `Forecasts` (`asset`, `base_date`, `created_at`, `model_version`, `target_series`, `horizons[].{h, target_date, q, prob_up}`) và thêm `input_snapshot_dt` (ngày `dt=` của snapshot clean đã dùng). Trường này chỉ nằm trong file S3 nên không chờ `contract.md`; champion sẽ có cùng trường khi contract thêm.
   - `dt=` trong key S3 là ngày chạy UTC, không bao giờ dùng thay `base_date`.
   - `created_at` giống champion vì cả hai tính trong cùng một lần gọi Lambda. Bằng chứng độc lập là `LastModified` của object S3 (do S3 đặt, code không sửa được) kết hợp `IfNoneMatch="*"` (không ghi đè). Job `rolling_8w` kiểm cả hai mốc theo cùng quy tắc D18: `created_at` và `LastModified` đều phải sớm hơn `target_date` 13:30 UTC.
2. **Cùng một tập chấm.** Champion và S1a chỉ được so trên đúng cùng tập `(asset, base_date, h)` có cả hai dự báo và target hợp lệ. Chỉ số của champion dùng để so được tính lại trên tập này, không lấy số `/accuracy/{asset}` đã công bố.
3. **Tách khỏi API.** `/accuracy/{asset}` và `LATEST_COMPLETED` chỉ dành cho champion. Kết quả so sánh champion–S1a lưu Parquet tại `eval/shadow_eval/run_id=<run_id>/`, không ghi DynamoDB, không qua API, đúng ADR-0011 mục 3 (chỉ để báo cáo).
