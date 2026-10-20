# DLinear forecasting — source MVP

Source này triển khai training/inference; **chưa train chính thức và chưa có validation 2019**. Reviewer cần duyệt source trước khi train. Không có weights hoặc Parquet đi kèm PR.

## Kiến trúc

Mỗi asset gold/GLD, silver/SLV, brent/BZ=F, wti/CL=F có model riêng. Input `[B,60,1]` chỉ gồm `log_return_1_end`. Centered moving average kernel 25 dùng replicate padding hai đầu; trend và seasonal mỗi nhánh `Linear(60,49)`, cộng và reshape `[B,7,7]`. Median + Softplus gaps bảo đảm phân vị không giảm theo thứ tự `[.05,.10,.25,.50,.75,.90,.95]`, horizons 1–7 phiên. Quantile gaps khởi tạo bằng targets train. Không đổi kiến trúc so với package Kaggle đã kiểm thử.

## Dependencies và khả năng tích hợp

- Returns PR #13 và `QUANTILE_LEVELS` đã có trong ZIP developer được cung cấp. Không sao chép Returns từ package Kaggle.
- **ZIP developer hiện chưa có Feature Builder `src/features/build.py`: phải tích hợp PR #14 đã sửa generator và missing publication trước khi chạy DLinear/CI.** PR DLinear không bổ sung hoặc sửa file đó. Không dùng fallback hay tự cắt window để né dependency.
- Metrics PR #11 và Walk-forward PR #12 không cần cho training; dùng ở bước đánh giá sau này. PR này không sửa các API đó.
- Requirements chính của developer đã có NumPy, pandas, pyarrow, calendar và Torch với phiên bản tương thích. Không sửa requirements chính hoặc CI workflow. Ba requirements DLinear là tập nhỏ tùy chọn cho training/test trên Kaggle hoặc NumPy runtime riêng; không thay thế lock/pins của toàn repository.

## Dữ liệu, split và chống leakage

Truyền đường dẫn clean `prices.parquet` và `rejected.parquet` từ CLI/Kaggle Input; không đưa chúng vào Git. Warm-up 2012–2013, origins train 2014–2018, tất cả bảy target phải hữu hạn và target dates <=2018-12-31. Validation 2019 và test 2020+ không tham gia fit weights, scaler hay quantile initialization.

`build_feature_frame()`/`make_windows()` của PR #14 là nguồn duy nhất tạo/cắt input. Không fill, interpolate hoặc drop missing trước khi cắt. Target từ Returns theo lịch đúng asset; rejected xử lý theo asset. Complete case đủ cả bảy horizons; đầu mút không hợp lệ bị loại, thiếu giữa hai đầu không tự hủy một target. Scaler fit trên inputs train hợp lệ, ddof=0, std=0 dùng 1; scale đúng một lần.

Kiểm tra `max_input_published_at` theo publication rule nguồn, UTC; thiếu metadata không được chấp nhận. Dùng latest clean snapshot + publication rule, không tuyên bố verified historical vintage/PIT. Fixed epochs, không early stopping trên 2019. Log n_expected/n_valid/n_excluded và lý do loại.

## Tests và smoke

Trong môi trường Python >=3.11, sau khi PR #14 đã có trong source:

```text
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m src.forecast.train_dlinear --help
```

Tập training-only tối thiểu: `python -m pip install -r requirements-dlinear-test.txt`; sau đó chạy `python -m pytest -q tests/test_dlinear.py tests/test_kaggle_package.py`.

Hai test file DLinear dùng fixtures nhỏ/tổng hợp, Parquet chỉ được tạo trong thư mục tạm khi chạy test. Không cần clean snapshot hay source manifest của package cũ. Tests giữ chống leakage, cutoff, scaler train-only, output shape, monotonic quantiles, gradient, parity tuyệt đối 1e-6 và load NumPy khi chặn Torch/SciPy/pandas. Test `test_external_inputs_smoke_train_export_and_parity` train một asset tổng hợp 32 mẫu, 1 epoch và export/load ngoài source; không tạo model bàn giao chính thức.

Nếu chưa có PR #14, import/collection DLinear sẽ lỗi rõ ràng; không skip các test này để làm CI xanh. Không coi bộ tests thành công khi đã bỏ dependency.

## CLI chung cho local và Kaggle

Đường dẫn bên dưới lấy từ biến môi trường/đường dẫn thực tế của người chạy; xem `--help`:

```text
python -m src.forecast.train_dlinear --asset gold --prices /path/to/prices.parquet --rejected /path/to/rejected.parquet --output-dir /path/to/models --epochs 20 --batch-size 64 --learning-rate 0.001 --device cpu
```

Thay ba `/path/to/...` bằng vị trí thật của file clean và nơi lưu model bên ngoài Git. `--asset all` train riêng bốn model; notebook gọi từng asset cho dễ theo dõi. Defaults là cấu hình thực nghiệm, chưa được chọn bằng validation. Seed tái lập trong cùng môi trường; không bảo đảm bit-identical trên mọi phiên bản/hardware. GPU chưa được kiểm chứng local.

## Kaggle repository notebook

Dùng `notebooks/train_dlinear_kaggle.ipynb`, không cần ZIP package Kaggle cũ. Add Input hai nguồn riêng: source repository đầy đủ đã có PR #14 + DLinear, và clean snapshot. Source Input có thể là thư mục hoặc ZIP repository. Data Input có thể là thư mục cặp prices/rejected cùng snapshot hoặc ZIP dữ liệu sạch. Notebook in candidates; nếu nhiều nguồn, đặt các biến override theo đúng đường dẫn in ra. Không đoán tên dataset và không tải market data.

Notebook chép source vào `/kaggle/working`, data Input chỉ đọc (nếu ZIP, giải nén hai Parquet vào Working). Dependencies chỉ được cài nếu thiếu. Các cell gọi CLI, audit dữ liệu và tests tổng hợp trước khi train. Chỉnh epochs/batch size/learning rate/seed/device ở cell cấu hình. CPU dùng được; GPU tùy chọn trong Settings và DEVICE. Không có logic model/training thứ hai trong notebook.

Khi train chính thức, cung cấp **mã commit nguồn thật** qua `SOURCE_COMMIT` hoặc `--source-commit`; không dùng Git/GitHub để tự lấy mã trong pipeline. Thiếu commit vẫn chạy thử được nhưng manifest ghi `commit=null`, `integration_eligible=false`. Commit có mặt không thay thế review hoặc bằng chứng vintage.

## Artifacts và inference

Mỗi asset/version có `weights.npz`, `config.json`, `scaler.json`, `manifest.json`; Fits metadata gồm fit_id, model_version, asset, train_end, max_training_target_date, trained_at thực tế, config_hash, commit. Không ghi đè version/fit đã có. Manifest có training settings, snapshot hashes, versions và parity. Notebook kiểm tra 16 file và tạo `trained-dlinear-models.zip` trong Working để người dùng tải, không upload tự động.

Sau train chỉ cần NumPy và `src.forecast.dlinear_numpy` cùng package init/artifacts:

```python
from src.forecast.dlinear_numpy import DLinearNumpy

runtime = DLinearNumpy.load(artifact_directory)
quantiles = runtime.predict(windows)  # raw windows [B,60,1], chưa scale
one_forecast = quantiles[0]  # [7,7]
```

`artifact_directory` và `windows` là thư mục model thực tế và output hợp lệ từ Feature Builder. Không scale lại hoặc normalize/sort quantiles lần nữa. NumPy runtime không import Torch/SciPy hoặc tự cắt windows.

Lưu data/artifacts ngoài Git hoặc trong các đường dẫn đã ignore như `data/lake/`, `models/`; `.gitignore` hiện có đã ignore models và weights npz/pth. Chỉ upload source/notebook/tests/docs/requirements. Không upload Parquet, manifests của model thử, checkpoint hoặc ZIP kết quả.

## Quan hệ với package Kaggle cũ

Bốn module model/data/NumPy/train được giữ nguyên bytes so với package đã bàn giao. Chỉ helper audit chuyển từ đường dẫn package cố định sang hai file ngoài repo, bỏ checksum manifest chuyên package; tests tích hợp dùng synthetic inputs; notebook nạp repository và data riêng. Những thay đổi launcher/helper không thay công thức, weights hoặc tập train khi cùng source dependency, inputs, settings và môi trường. Không coi toàn bộ hai package là giống nhau: notebook/helper/tests khác nhau.

ZIP Kaggle hiện tại không bị sửa và vẫn dùng được cho phiên bản cũ. Sau khi PR được duyệt, nên tạo lại gói Kaggle từ source đã chốt + dữ liệu ngoài Git để đồng nhất mã commit/launcher; không cần train lại chỉ vì thay đường dẫn audit. Actual Kaggle/GPU và cài dependencies mới qua Internet vẫn cần kiểm chứng.
