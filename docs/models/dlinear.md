# DLinear forecasting — source MVP

Source này triển khai training/inference; **chưa train chính thức và chưa có validation 2019**. Reviewer cần duyệt source trước khi train. Không có weights hoặc Parquet đi kèm PR.

## Kiến trúc

Mỗi asset gold/GLD, silver/SLV, brent/BZ=F, wti/CL=F có model riêng. Input `[B,60,1]` chỉ gồm `log_return_1_end`. Centered moving average kernel 25 dùng replicate padding hai đầu; trend và seasonal mỗi nhánh `Linear(60,49)`, cộng và reshape `[B,7,7]`. Median + Softplus gaps bảo đảm phân vị không giảm theo thứ tự `[.05,.10,.25,.50,.75,.90,.95]`, horizons 1–7 phiên. Quantile gaps khởi tạo bằng targets train. Không đổi kiến trúc so với package Kaggle đã kiểm thử.

**Quy tắc normalize theo ADR-0008:** DLinear tạo phân vị không giảm nhờ median–Softplus head, nhưng tầng Lambda Predict vẫn phải kiểm tra `crossed_raw` trên output thô và gọi `normalize_quantiles()` **đúng một lần** sau khi model dự báo. Với DLinear hợp lệ, phép normalize thông thường là no-op; vẫn phải thực hiện để thống nhất contract và ghi nhận crossing. Sau bước này, các tầng downstream chỉ kiểm tra, **không normalize/sort lần thứ hai**.

## Dependencies và khả năng tích hợp

- Returns PR #13 và `QUANTILE_LEVELS` đã có trong ZIP developer được cung cấp. Không sao chép Returns từ package Kaggle.
- **PR #14 Feature Builder đã được Khải xác nhận có trong `origin/developer` mới.** DLinear phụ thuộc `src/features/build.py` có bản sửa `invalid_dates` generator và thiếu publication metadata. Khi kiểm thử/huấn luyện, phải sử dụng source developer đã tích hợp PR #14; không dùng snapshot developer cũ, fallback hoặc tự cắt window để né dependency. PR DLinear không bổ sung hoặc sửa Feature Builder.
- Metrics PR #11 và Walk-forward Contract PR #12 không cần cho training; dùng ở bước đánh giá sau này. PR này không sửa các API đó.
- Requirements chính của developer đã có NumPy, pandas, pyarrow, calendar và Torch với phiên bản tương thích. Không sửa requirements chính hoặc CI workflow. Ba requirements DLinear là tập nhỏ tùy chọn cho training/test trên Kaggle hoặc NumPy runtime riêng; không thay thế lock/pins của toàn repository.

## Dữ liệu, split và chống leakage

Truyền đường dẫn clean `prices.parquet` và `rejected.parquet` từ CLI/Kaggle Input; không đưa chúng vào Git. Warm-up 2012–2013, origins train 2014–2018, tất cả bảy target phải hữu hạn và target dates `<=2018-12-31`. Validation 2019 và test 2020+ không tham gia fit weights, scaler hay quantile initialization.

`build_feature_frame()`/`make_windows()` của PR #14 là nguồn duy nhất tạo/cắt input. Không fill, interpolate hoặc drop missing trước khi cắt. Target từ Returns theo lịch đúng asset; rejected xử lý theo asset. Complete case đủ cả bảy horizons; đầu mút không hợp lệ bị loại, thiếu giữa hai đầu không tự hủy một target. Scaler fit trên inputs train hợp lệ, `ddof=0`, `std=0` dùng 1; scale đúng một lần.

**Quy tắc thống kê InputScaler:** `InputScaler.fit()` tính mean/std trên **toàn bộ giá trị của các cửa sổ train chồng nhau**, không phải trên chuỗi phiên đã khử trùng lặp. Một phiên có thể được tính nhiều lần vì xuất hiện trong nhiều cửa sổ (phiên ở giữa có thể xuất hiện khoảng 60 lần). Đây là hành vi code đã được Khải review và **giữ nguyên**, không thay scaler chỉ để mỗi phiên đếm một lần. Toàn bộ những cửa sổ này phải thuộc tập train hợp lệ.

Kiểm tra `max_input_published_at` theo publication rule nguồn, UTC; thiếu metadata không được chấp nhận. Dùng latest clean snapshot + publication rule, không tuyên bố verified historical vintage/PIT. Fixed epochs, không early stopping trên 2019. Log `n_expected`/`n_valid`/`n_excluded` và lý do loại.

## Tests và smoke

Trong môi trường Python >=3.11, sau khi source developer đã có PR #14:

```text
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m src.forecast.train_dlinear --help
```

Tập training-only tối thiểu: `python -m pip install -r requirements-dlinear-test.txt`; sau đó chạy `python -m pytest -q tests/test_dlinear.py tests/test_kaggle_package.py`.

Hai test file DLinear dùng fixtures nhỏ/tổng hợp, Parquet chỉ được tạo trong thư mục tạm khi chạy test. Không cần clean snapshot hay source manifest của package cũ. Tests giữ chống leakage, cutoff, scaler train-only, output shape, monotonic quantiles, gradient, parity tuyệt đối `1e-6` và load NumPy khi chặn Torch/SciPy/pandas. Test `test_external_inputs_smoke_train_export_and_parity` train một asset tổng hợp 32 mẫu, 1 epoch và export/load ngoài source; không tạo model bàn giao chính thức.

**CI của PR phải xanh trên commit hiện tại đã đồng bộ với developer có PR #14.** Kết quả `284 passed` do Khải báo khi chạy bản gộp là bằng chứng kiểm thử tích hợp, nhưng không thay thế GitHub Actions của PR. Lỗi collection do thiếu `src.features.build` trong snapshot cũ không còn áp dụng sau khi đồng bộ; nếu Ruff báo `I001`, phải xử lý theo log trên commit hiện tại. Không skip tests để CI xanh.

## CLI chung cho local và Kaggle

Đường dẫn bên dưới lấy từ biến môi trường/đường dẫn thực tế của người chạy; xem `--help`:

```text
python -m src.forecast.train_dlinear --asset gold --prices /path/to/prices.parquet --rejected /path/to/rejected.parquet --output-dir /path/to/models --epochs 20 --batch-size 64 --learning-rate 0.001 --device cpu
```

Thay ba `/path/to/...` bằng vị trí thật của file clean và nơi lưu model bên ngoài Git. `--asset all` train riêng bốn model; notebook gọi từng asset cho dễ theo dõi. Defaults là cấu hình thực nghiệm, chưa được chọn bằng validation. Seed tái lập trong cùng môi trường; không bảo đảm bit-identical trên mọi phiên bản/hardware. GPU chưa được kiểm chứng local.

## Kaggle repository notebook

Dùng `notebooks/train_dlinear_kaggle.ipynb`, không cần ZIP package Kaggle cũ. Add Input hai nguồn riêng: source repository đầy đủ đã có PR #14 + DLinear, và clean snapshot. Source Input có thể là thư mục hoặc ZIP repository. Data Input có thể là thư mục cặp prices/rejected cùng snapshot hoặc ZIP dữ liệu sạch. Notebook in candidates; nếu nhiều nguồn, đặt các biến override theo đúng đường dẫn in ra. Không đoán tên dataset và không tải market data.

**Dataset giá trên Kaggle phải được đặt Private** theo yêu cầu review của Khải/ADR-0005. Trước khi train, người dùng phải tự kiểm tra trạng thái visibility của dataset; tài liệu này không xác nhận dataset hiện tại đang Private.

Notebook chép source vào `/kaggle/working`, data Input chỉ đọc (nếu ZIP, giải nén hai Parquet vào Working). Dependencies chỉ được cài nếu thiếu. Các cell gọi CLI, audit dữ liệu và tests tổng hợp trước khi train. Chỉnh epochs/batch size/learning rate/seed/device ở cell cấu hình. CPU dùng được; GPU tùy chọn trong Settings và DEVICE. Không có logic model/training thứ hai trong notebook.

**Train chính thức chỉ sau khi PR DLinear được review, CI xanh và merge vào `developer`.** Dùng source đúng phiên bản đã merge và truyền **SHA commit merge của PR DLinear trên `developer`** qua `SOURCE_COMMIT` hoặc `--source-commit`. Không dùng SHA của nhánh cũ hoặc một chuỗi tùy ý. Không sử dụng Git/GitHub bên trong pipeline để tự lấy mã. Thiếu commit vẫn chạy thử được nhưng manifest ghi `commit=null`, `integration_eligible=false`. Việc có commit không thay thế review hoặc bằng chứng vintage.

## Artifacts và inference

Mỗi asset/version có `weights.npz`, `config.json`, `scaler.json`, `manifest.json`; Fits metadata gồm `fit_id`, `model_version`, `asset`, `train_end`, `max_training_target_date`, `trained_at` thực tế, `config_hash`, `commit`. Không ghi đè version/fit đã có. Manifest có training settings, snapshot hashes, versions và parity. Notebook kiểm tra 16 file và tạo `trained-dlinear-models.zip` trong Working để người dùng tải, không upload tự động.

Sau train, inference DLinear dùng NumPy và `src.forecast.dlinear_numpy` cùng package init/artifacts:

```python
from src.forecast.dlinear_numpy import DLinearNumpy

runtime = DLinearNumpy.load(artifact_directory)
quantiles = runtime.predict(windows)  # raw windows [B,60,1], chưa scale thủ công
one_forecast = quantiles[0]  # [7,7]
```

`artifact_directory` và `windows` là thư mục model thực tế và output hợp lệ từ Feature Builder. `DLinearNumpy` dùng scaler đã lưu; bên ngoài **không scale input thêm một lần** và không tự cắt windows. `predict()` trả phân vị DLinear; khi đưa kết quả vào Lambda Predict, tầng đó vẫn phải ghi nhận `crossed_raw` trên output thô và gọi `normalize_quantiles()` **đúng một lần** theo ADR-0008, rồi các tầng sau chỉ validate, không sort lại.

Lưu data/artifacts ngoài Git hoặc trong các đường dẫn đã ignore như `data/lake/`, `models/`; `.gitignore` hiện có đã ignore models và weights npz/pth. Chỉ upload source/notebook/tests/docs/requirements. Không upload Parquet, manifests của model thử, checkpoint hoặc ZIP kết quả.

**Bàn giao artifacts:** Khi Tuấn cấp quyền S3, lưu riêng tư theo đường dẫn `models/<asset>/<model_version>/`. Trong lúc chưa có quyền, gửi `trained-dlinear-models.zip` qua **Drive riêng do Khải chỉ định**; không sử dụng liên kết công khai. Không upload ZIP weights vào GitHub hoặc dataset Kaggle công khai.

## Quan hệ với package Kaggle cũ

Bốn module model/data/NumPy/train được giữ nguyên bytes so với package đã bàn giao tại thời điểm chuẩn bị PR. Chỉ helper audit chuyển từ đường dẫn package cố định sang hai file ngoài repo, bỏ checksum manifest chuyên package; tests tích hợp dùng synthetic inputs; notebook nạp repository và data riêng. Những thay đổi launcher/helper không thay công thức, weights hoặc tập train khi cùng source dependency, inputs, settings và môi trường. Không coi toàn bộ hai package là giống nhau: notebook/helper/tests khác nhau.

ZIP Kaggle cũ không bị sửa và chỉ phản ánh source ở thời điểm đóng gói. **Để train chính thức, ưu tiên notebook repository với source đã merge PR #14 và PR DLinear, không dùng ZIP Kaggle cũ như nguồn code chuẩn.** Sau khi PR được duyệt, có thể tạo lại gói Kaggle từ source đã chốt + dữ liệu ngoài Git để đồng nhất mã commit/launcher. Không cần train lại chỉ vì đổi đường dẫn audit; thay đổi code ảnh hưởng model, dữ liệu, scaler hoặc target thì phải đánh giá lại nhu cầu train. Actual Kaggle/GPU và cài dependencies mới qua Internet vẫn cần kiểm chứng.
