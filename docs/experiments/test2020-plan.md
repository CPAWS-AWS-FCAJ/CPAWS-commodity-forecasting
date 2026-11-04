# Tập test 2020 → nay: kế hoạch chạy một lần (chốt trước khi chạy)

- Ngày: 31/10/2026; sửa 2/11/2026 theo review của Long ở #75
- Người viết: Khải (bản nháp do Claude soạn); người duyệt: Long
- Trạng thái: **Đã chốt (#75, merge 03/11/2026 09:59Z).** Mục 8.1 điền theo quy tắc mục 2; chưa chạy test2020.
- Căn cứ: ADR-0008 (chia dữ liệu, chỉ số), ADR-0010 (S1a), ADR-0011 (champion/challenger), ADR-0012 (dừng dò mô hình), họp 30/10 điểm 19 và 21.

## 0. Mục đích

ADR-0008 dành 2020 → nay làm tập test, chỉ chạy một lần sau khi khóa tham số. Validation 2019 đã dùng 4 lần với 13 cấu hình (ADR-0012), nên tập test là bằng chứng ngoài mẫu duy nhất chưa bị nhìn. Lần chạy này trả lời một câu: mô hình đang chạy trên sản phẩm và challenger của nó hoạt động thế nào trên dữ liệu chưa từng dùng để chọn.

## 1. Mô hình (chốt)

| Mô hình | Vai trò | Tham số |
|---|---|---|
| `baseline-q252` | Champion, mốc của mọi `pinball_skill` | Phân vị thực nghiệm 252 phiên nhân quả, không học |
| S1a (`s1a-l094`) | Challenger (ADR-0010, 0011) | λ = 0,94, kẹp k_t ∈ [0,5; 2,0], chọn trên 2019 rồi khóa |
| naive (return = 0) | Mẫu số của `mae_ratio_vs_naive` | Không có |

Không chạy K3, K3b khác S1a, K4, DLinear: đều đã thua mốc trên validation, chạy thêm không giúp quyết định nào và chỉ tăng số cấu hình xem trên test.

## 2. Dữ liệu và khoảng thời gian (chốt)

- Bản clean: `clean/prices/dt=<DT>/`, DT là snapshot mới nhất có trên S3 tại lúc merge kế hoạch này. DT, SHA-256 của bản clean và lineage (nguồn yfinance, mã chuỗi, commit `src/data/` tạo bản clean) ghi vào mục 8 và vào `claim.json` **trước khi chạy**; runner kiểm lại SHA-256 khi nạp và dừng nếu lệch.
- Ngày gốc: từ 2020-01-02 đến 2026-10-23 (phiên cuối trước base 26/10, ngày đầu của luồng chạy thật), theo lịch của từng tài sản (NYSE cho GLD/SLV, CME cho BZ=F/CL=F).
- Mốc cắt ngày đích: 2026-10-23. Ngày gốc có ngày đích sau mốc này bị loại và được đếm, không lấy giá sau mốc.
- **Chỉ dùng thông tin có tại ngày gốc.** Với mỗi h, `baseline-q252` chỉ dùng return h phiên đã hoàn tất (ngày đích ≤ ngày gốc); EWMA của S1a chỉ dùng return 1 phiên đến ngày gốc. Lịch sử khởi động dùng return trước 2020 theo cùng quy tắc.
- **Giới hạn PIT:** bản clean mới nhất là giá tải lại, không phải ảnh chụp tại từng ngày gốc, nên không chứng minh PIT lịch sử đầy đủ (Yahoo có thể sửa giá cũ). Báo cáo ghi rõ giới hạn này.
- Target và quy tắc dữ liệu giữ nguyên ADR-0008 và `src/data/`: log return h phiên, h = 1–7; giá ≤ 0 hoặc thiếu → NaN; không forward-fill.
- **WTI 20/4/2020:** nằm trong giai đoạn biến động COVID (mục 4) nhưng mọi cặp có giá ≤ 0 ở ngày gốc hoặc ngày đích không được chấm; báo cáo số cặp bị loại theo tài sản × h.
- Dầu báo cáo hai mẫu `all` và `excl_roll` (cửa sổ roll tính theo kỳ đánh giá, như K4 mục 8).

## 3. Chỉ số (ADR-0008 mục 5)

### 3.1 Chỉ số chính (chốt định nghĩa)

- **Mặt nạ chung:** một bộ (tài sản, ngày gốc, h) được chấm khi target hợp lệ và cả `baseline-q252` lẫn S1a đều có dự báo. Hai mô hình luôn chấm trên đúng cùng một tập dòng; runner kiểm số dòng của hai mô hình bằng nhau theo từng tài sản × h × mẫu, lệch thì dừng.
- **Skill theo h:** `pinball_skill(a, h) = 1 − L_S1a(a, h) / L_base(a, h)`, L là pinball loss trung bình 7 phân vị trên các dòng của mặt nạ chung (đúng hàm `src/eval/metrics.pinball_skill`).
- **Chỉ số chính theo tài sản:** trung bình cộng 7 skill theo h, `S(a) = (1/7) Σ_h pinball_skill(a, h)`, trên mẫu `all`. Lấy trung bình 7 skill (không gộp loss) để mỗi kỳ hạn có trọng số như nhau, vì loss h = 7 lớn hơn h = 1 nhiều lần; đơn vị đánh giá vẫn là nhóm tài sản × h như ADR-0011. Nếu một h không có dòng nào hoặc `L_base(a, h) = 0` thì `S(a)` là undefined (không bỏ bớt h để tính tiếp), báo lý do.
- **4 giả thuyết chính** (một cho mỗi tài sản, mẫu `all`): H0: S(a) ≤ 0, H1: S(a) > 0 (một phía).
- **Bootstrap:** circular moving-block bootstrap trên lịch hợp nhất NYSE/CME (như `walk_forward.py`), block 20, B = 2000, seed cố định ghi trong config. **Một kế hoạch rút mẫu ngày dùng chung** cho mọi tài sản và mọi h, nên giữ phụ thuộc giữa kỳ hạn và giữa tài sản. Mỗi lần rút tính lại `S*(a)` từ các dòng của ngày được rút. Lần rút nào cho giá trị không hữu hạn thì CI undefined (theo `block_bootstrap_ci`), không bỏ lần rút.
- **p-value (bootstrap căn giữa theo H0):** mỗi lần rút tính `T*(a) = S*(a) − Ŝ(a)`, với Ŝ(a) là giá trị trên mẫu gốc; phân phối của T* xấp xỉ phân phối của Ŝ(a) − S(a), nên dùng làm phân phối dưới H0 (S(a) = 0). p một phía `p(a) = (1 + #{T*(a) ≥ Ŝ(a)}) / (B + 1)`. Không dùng tỷ lệ lần rút có S* ≤ 0 làm p-value.
- **Holm** qua 4 tài sản trên 4 p-value trên, α = 0,05. Kết luận "S1a tốt hơn mốc ở tài sản a" chỉ khi p Holm của a < 0,05.
- **CI 95% percentile** của `S*(a)` báo kèm để mô tả độ bất định, không dùng thay kiểm định.
- Các con số trên chỉ để báo cáo (mục 5); không dùng đổi champion.

### 3.2 Bất biến của S1a (kiểm trước khi tính chỉ số, sai thì dừng)

- q50 của S1a trùng `baseline-q252` từng bit trên mặt nạ chung (ADR-0010: S1a co giãn quanh trung vị của mốc).
- Vì vậy `mae_ratio_vs_naive` và `sign_accuracy` của hai mô hình phải bằng nhau.
- `prob_up` của S1a tính lại từ 7 phân vị của S1a bằng cùng hàm `prob_up` như production, không chép từ mốc.

### 3.3 Chỉ số phụ (báo cáo, không dùng chọn kết quả)

- 28 skill theo tài sản × h, kèm CI cùng kế hoạch bootstrap.
- Hiệu chỉnh: `quantile_hit_rates`, `coverage_80`, `width_80`, `width_80_pct`, `interval_score_80`, cho cả hai mô hình.
- Xác suất tăng: `brier_skill`.
- Phụ: `mae_ratio_vs_naive`, `sign_accuracy` kèm `up_rate`.
- DM (HAC, HLN) theo chính sách khoảng trống hiện có trong `walk_forward.py` (họ Holm 28 nhóm cho `all`, 14 cho `excl_roll`); chính sách mới hoãn sau 22/11 (điểm 21), báo cáo rõ các nhóm DM bị chặn.
- Không dùng MAPE, RMSE hay sai số trên mức giá.

## 4. Báo cáo bổ sung (chỉ báo cáo, không dùng chọn kết quả tốt nhất)

- Mẫu `excl_roll` cho dầu.
- Theo năm 2020, 2021, …, 2026.
- Hai giai đoạn biến động: 2020-02-15 → 2020-05-31 (COVID, gồm WTI âm) và 2022-02-15 → 2022-04-30 (Nga – Ukraine).
- Độ nhạy CI theo block 10 và 40.
- Số ngày gốc hợp lệ, số cặp bị loại theo lý do, theo tài sản × h × mẫu.

Kết luận chính chỉ dựa trên mục 3.1 (block 20, mẫu `all`); các mục trên không thay thế kết luận chính dù cho kết quả khác.

## 5. Kết quả dùng để làm gì (chốt trước khi chạy)

- Chỉ dùng cho báo cáo cuối và buổi bảo vệ.
- **Không đổi champion trước 22/11**, kể cả khi S1a có cận dưới CI > 0 ở tài sản nào đó (ADR-0011, họp 30/10 điểm 19). Muốn đổi champion sau đó phải có ADR mới.
- Kết quả xấu cho `baseline-q252` cũng không đổi sản phẩm trước 22/11; ghi trung thực vào báo cáo.
- Không có lần chạy thứ hai, không thêm mô hình hay cấu hình, không sửa thiết kế sau khi xem kết quả.

## 6. Chạy một lần

- Code: runner theo mẫu stage val2019 của `run_k4.py` (phần chặn, `started.json`, `verified_result`, SHA-256 từng file), `run_id = test2020` cố định. Code và test merge vào `developer` trước khi chạy; không dùng dữ liệu 2020 → nay khi viết hay test code (test dùng dữ liệu tổng hợp hoặc ≤ 2019).
- `claim.json` ghi trước khi chạy: commit (sạch), DT và SHA-256 bản clean, lineage (mục 2), mốc cắt, block, B, seed, `config_hash`, người chạy, thời điểm. Ghi lên `s3://cpaws-dev-lake/eval/test2020/claim.json` bằng `--if-none-match "*"`; `pip freeze` vào `env.txt`.
- Chạy xong: tải cả thư mục kèm SHA-256 lên `eval/test2020/`, báo ở PR kế hoạch.
- **Chạy lỗi giữa chừng:** không tự chạy lại, không đổi cấu hình. Ghi lỗi vào `failure.json` cạnh `claim.json`; cả nhóm quyết và ghi lý do thành mục mới của file này trước khi chạy lại (nếu có).
- Người chạy: Long, trên một máy và một venv. Khải review kết quả.
- Claude không xem, không tóm tắt kết quả 2020 → nay (quy tắc project).

## 7. Lịch

- Kế hoạch: PR #75, merge trước 10/11.
- Code runner: trước 15/11.
- Chạy: tuần 16–22/11, trước đóng băng.

## 8. Ghi trước khi chạy (quy tắc tại mục 2 và 6; snapshot đã khóa, execution metadata khóa trước lần chạy)

### 8.1. Snapshot clean đã khóa

- Mốc khóa snapshot: `2026-11-03T09:59:00Z`, thời điểm merge PR #75. Đây là mốc chọn snapshot, **khác** target cutoff `2026-10-23` của evaluation.
- DT đã chọn: **`2026-10-31`**.
- S3 prefix: `s3://cpaws-dev-lake/clean/prices/dt=2026-10-31/`.
- S3 Versioning: **Enabled**.
- Cả ba object dưới đây có `LastModified=2026-10-31T12:15:43Z`; không có delete marker trong output kiểm tra toàn prefix bên dưới.

| File | SHA-256 của raw bytes | VersionId | Size (bytes) |
|---|---|---|---:|
| `prices.parquet` | `49dfc745881a38a07bd40b5f722bb2d3f123a7ea0aa1d197fd12ea1ccc954473` | `XSqcFlfGvDZzMrQk43NorSBIYKmgnV4J` | 201081 |
| `rejected.parquet` | `630dbe9889e5d1d0d215c01f8c3a34e951f1a6d3f12bd5ba7fe261484e388f2e` | `YOzT5FhCZXmjBXH26a0zYdiwEe_A9TBU` | 5693 |
| `quality.json` | `cca4fd293c81028af8948420769638ba5b4c93379be74db7f91d5d6067584f30` | `z2kWzgePRwjaMMtLbH_FB4bvKthytYdl` | 13934 |

S3 URI của các object đã khóa:

- `s3://cpaws-dev-lake/clean/prices/dt=2026-10-31/prices.parquet`
- `s3://cpaws-dev-lake/clean/prices/dt=2026-10-31/rejected.parquet`
- `s3://cpaws-dev-lake/clean/prices/dt=2026-10-31/quality.json`

**Bằng chứng S3 Versioning.** Long hoàn thành truy vấn toàn prefix `clean/prices/` của bucket `cpaws-dev-lake` bằng profile `cpaws-dev` lúc **`2026-11-04T07:45:54Z`**. Lệnh đã thực hiện:

```powershell
aws s3api list-object-versions `
  --bucket cpaws-dev-lake `
  --prefix clean/prices/ `
  --profile cpaws-dev `
  --query '{Versions:Versions[].{Key:Key,VersionId:VersionId,LastModified:LastModified,Size:Size,IsLatest:IsLatest},DeleteMarkers:DeleteMarkers[].{Key:Key,VersionId:VersionId,LastModified:LastModified,IsLatest:IsLatest}}' `
  --output json `
  --no-cli-pager
```

Bằng chứng đầy đủ: [S3 object version history](test2020-s3-versions-evidence.json), gồm **48 object versions thuộc 12 snapshot** và không có delete marker trong kết quả truy vấn (`DeleteMarkers=null`). Các versions lịch sử của DT 2026-10-28 được giữ nguyên trong file bằng chứng.

Đối chiếu timestamps và lịch sử versions trong output:

- Không có object version nào dưới `clean/prices/` có `LastModified` trong khoảng **(`2026-10-31T12:15:43Z`, `2026-11-03T09:59:00Z`]**; không có phiên bản ghi đè của ba key DT 31/10 trong khoảng này.
- Ba VersionId của DT `2026-10-31` trong bảng trên là các phiên bản còn hiệu lực tại cutoff; snapshot đủ cả ba file. `IsLatest` phản ánh thời điểm truy vấn, không được dùng thay lịch sử timestamps để xác định phiên bản tại cutoff.
- Ba object versions của DT `2026-11-03` đều có `LastModified=2026-11-03T12:15:28Z`, sau cutoff, nên snapshot này bị loại.

Theo output toàn prefix, snapshot đầy đủ mới nhất tồn tại tại cutoff là **`dt=2026-10-31`**. Ba file đã được tải theo VersionId và đối chiếu raw-byte SHA-256/kích thước với `snapshot-sha256.json`; các giá trị khóa trong bảng được giữ nguyên.

**Metadata clean và lineage.** `quality.json` ghi `run.run_at_utc=2026-10-31T12:15:20+00:00` (tương đương `2026-10-31T12:15:20Z`) và `status=ok`. `run.fetch_log` ghi bốn chuỗi target từ yfinance: gold→GLD, silver→SLV, wti→CL=F, brent→BZ=F. Log cũng ghi dữ liệu tham chiếu EIA (RWTC, RBRTE) và nguồn phụ trợ yfinance (VND=X, GC=F, SI=F), NBP (nbp_gold); các nguồn này không thay chuỗi target đã chốt.

Lineage `data_commit` của Lambda `cpaws-dev-ingest` tại lần clean 31/10 đang chờ xác minh full Git SHA và deployment reference từ Tuấn/Tiến; phải hoàn tất trước official claim.

### 8.2. Thông tin sẽ khóa trước lần chạy chính thức

- Runner commit sạch: chưa khóa; chỉ điền sau khi runner và protocol cuối cùng được review/merge.
- `config_hash`: chưa tính/chưa khóa; chỉ tính sau khi PR cập nhật tài liệu này đã merge và runner được freeze. Không tính hash chính thức trong lần sửa tài liệu này.
- Seed: ghi giá trị đã được review trong locked runner config và execution metadata trước claim; không tự chọn, đổi hoặc suy giá trị từ snapshot.
- Execution metadata theo mục 6: đủ lineage (bao gồm commit `src/data/` còn thiếu), snapshot DT/ba SHA-256, mốc cắt, block, B, seed, runner commit, `config_hash`, người chạy và thời điểm; lưu môi trường theo quy tắc đã chốt. Không tạo claim hoặc bắt đầu evaluation khi các điều kiện còn thiếu.

## 9. Sửa đổi

- 04/11/2026 (hoàn thiện metadata và xác nhận chính sách hiện hành): khóa snapshot `dt=2026-10-31` theo mốc merge #75 `2026-11-03T09:59:00Z` và bằng chứng tại mục 8. Nhóm chấp nhận dùng DM calendar-gap policy đang được triển khai trong `walk_forward.py` cho test2020: với h > 1, DM bị chặn nếu chuỗi ngày đánh giá có internal session gaps; nhóm bị chặn phải được ghi nhận undefined/không đủ điều kiện, không phát sinh p-value giả. Chính sách amplitude-modulated đã được đặc tả trong Accuracy Schema nhưng chưa phải implementation đang sử dụng. Giữ nguyên chuỗi `DM_GAP_POLICY=block_internal_session_gaps_for_h_gt_1_pending_Khai_review`, không đổi tên chỉ để cập nhật trạng thái; không sửa `walk_forward.py`, `metrics.py` hoặc thuật toán DM. Quyết định này xác nhận phương pháp hiện hành cho lần chạy, không tạo phương pháp kiểm định mới. Tham chiếu: [Walk-forward implementation](../../src/eval/walk_forward.py), [Accuracy Schema](../api/accuracy-schema.md).
- 3/11/2026 (review Long lần 2, #75): p-value đổi sang bootstrap căn giữa theo H0; Holm áp trên p-value này; CI percentile chỉ để mô tả.
- 2/11/2026 (review Long, #75): chốt định nghĩa chỉ số chính (trung bình 7 skill theo h, mặt nạ chung, xử lý undefined); bootstrap dùng chung kế hoạch rút mẫu, 4 giả thuyết một phía, p-value và Holm; bất biến S1a; khóa DT/SHA-256/lineage trong `claim.json`, giới hạn PIT; WTI 20/4/2020; quy trình khi chạy lỗi; B từ 1000 lên 2000; tách rõ chỉ số phụ và báo cáo bổ sung.
