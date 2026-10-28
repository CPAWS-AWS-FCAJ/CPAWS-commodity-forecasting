# Tái lập audit WTI/Brent 2016

## Inputs và kiểm tra phiên bản
Audit ngày 2026-10-28; chỉ dùng 4 ZIP được đính kèm. Đường dẫn tuyệt đối, hash toàn ZIP và từng member được ghi ở `scripts/input_inventory.json`. File này là danh sách hash đóng băng: run_audit.py từ chối input thay đổi, không âm thầm dùng một bản mới cùng tên. Nếu nhận source mới, cần một output/audit lineage mới.

| path | SHA-256 |
|---|---|
| C:\Users\Tien Long\Downloads\CPAWS-commodity-forecasting-developer (2).zip | 5ef0987d4c23979e9831d5df9069f2279b6c914a06274485dcd422d133c68021 |
| C:\Users\Tien Long\Downloads\data-20261018T113233Z-1-001.zip | b94b20beb7136c0db3598dfb9577b2c904572cbf3137cdc8da16d35d77b2d3a0 |
| C:\Users\Tien Long\Downloads\CPAWS_Validation_2019_Drive_Review.zip | dd616f2aa2f4807b9b1099c60f596e0b85b77c393af5c03a922e6a32bb08d934 |
| C:\Users\Tien Long\Downloads\cpaws-validation-2019-diagnostics-results.zip | 2a71860d6f7c43db71c43495910a28aa30da5cfde19da4a5a99ca3a2939126eb |

Các tên trong prompt khác hậu tố tên file đính kèm; đã dùng đường dẫn đính kèm người dùng chỉ định. Không truy cập repository khác. Hai ZIP kết quả có 8 member nội dung giống nhau, chỉ dùng ZIP3. 13 module code hash so với manifest được lưu trong summary: chỉ baselines.py khác, không gọi baseline/evaluation.

## Snapshot và nguồn chính
Snapshot `data/lake/clean/prices/dt=2026-10-09/` trong ZIP2:

| file | SHA-256 |
|---|---|
| prices.parquet | 21bb22cd5da99f6d5cb8ccc7adee67f58a5178521692513e7b37133249692a83 |
| rejected.parquet | 753b747d294bd309fdb90e80c5c2f4104f0a48f000337eb576e9ff92390e984f |
| quality.json | 7398a4f48953ef3b92716ea9383136036100375fd898aafa135905c6d1b2bd57 |

Raw: mọi CL_F/BZ_F CSV và CSV.GZ trong ZIP2; EIA RWTC/RBRTE JSON.GZ và p0 JSON.GZ. Ngày 09/10 là incremental, không bao phủ 2016/2018. Các dòng lân cận và phạm vi file có ở scripts/evidence.json. XLS EIA có trong ZIP nhưng không dùng vì JSON đã đủ cho câu hỏi presence/reference; không giả định XLS có cùng nội dung. quality được đối chiếu counts theo năm bằng asset_report().

Source ZIP1: src/data/calendars.py, config.py, clean.py, quality.py, storage.py; src/features/build.py; src/forecast/returns.py; src/eval/walk_forward.py và metrics.py. Tài liệu đọc từ ZIP1: docs/adr/0005-price-data-sources.md; docs/adr/0008-target-quantiles-evaluation.md; docs/api/accuracy-schema.md; docs/eval/walk-forward-contract.md. Kết quả ZIP3: forecasts, detail, accuracy, model_comparison, evaluation_manifest/log, CSV diagnostics/report và SHA256SUMS.

## Môi trường
Local: `{"python": "3.11.15", "numpy": "2.4.6", "pandas": "3.0.6", "pandas_market_calendars": "5.5.0", "pyarrow": "25.0.1", "scipy": "1.17.0", "pytest": "9.1.1"}`.
Kaggle manifest: `{"python": "3.13.15", "numpy": "2.1.3", "pandas": "2.3.3", "scipy": "1.16.3", "pyarrow": "23.0.1", "pandas_market_calendars": "5.5.0", "tzdata": "2026.3"}`.
Python đã dùng: `C:/Users/Tien Long/Downloads/CPAWS-commodity-forecasting-docs-adr-0008-review-fixes/CPAWS-commodity-forecasting-docs-adr-0008-review-fixes/.venv/Scripts/python.exe`.

Không cài thêm packages hoặc gọi mạng. Để tái lập máy khác cần Python/packages tương ứng, các ZIP có đúng hash, và môi trường có sẵn pytest/numpy/pandas/scipy/pyarrow/pandas_market_calendars.

## Lệnh chạy (PowerShell)
Giải nén ZIP bàn giao; cd vào thư mục wti_brent_2016. Thay đường dẫn Python và Downloads nếu cần. `run_audit.py` đọc ZIP, tạo source_reference cục bộ từ ZIP1 và đối chiếu từng byte trước import; không import repository ngoài.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$auditPython='C:/Users/Tien Long/Downloads/CPAWS-commodity-forecasting-docs-adr-0008-review-fixes/CPAWS-commodity-forecasting-docs-adr-0008-review-fixes/.venv/Scripts/python.exe'
& $auditPython scripts/run_audit.py --input-dir 'C:/Users/Tien Long/Downloads'
Push-Location source_reference
& $auditPython -m pytest -q -p no:cacheprovider tests/test_data_clean_quality.py tests/test_returns_adr0008.py tests/test_features_build.py --junitxml=../scripts/pytest_results.xml *> ../scripts/pytest_output.txt
Pop-Location
& $auditPython scripts/build_reports.py
```

Lệnh cuối tạo ZIP ở thư mục cha của output. Source_reference là working copy tái tạo được từ ZIP1, không nằm trong ZIP bàn giao; không chứa dữ liệu input/model thay thế. Các lần chạy chỉ ghi vào output và ZIP bàn giao, không ghi input ZIP/source chính thức.

## Kết quả thực chạy
- 1482 assertions audit đạt, 0 fail.
- Pytest: 68 passed, 0 failed, 0 errors, 0 skipped. Xem scripts/pytest_output.txt và pytest_results.xml.
- Raw evidence 6 cặp; CSV impact 1178 dòng, gồm target pairs, feature cause links và observed forecasts. Counts chồng lấn phải distinct theo đối tượng, không tổng gộp tất cả.
- Hash toàn bộ ZIP gốc kiểm tra trước/sau; hash input/member/CSV output có trong summary; ZIP được kiểm CRC và so byte với từng deliverable.
- Không chạy inference, train/retrain, K3/K3b, metrics/evaluate, full validation, Git/GitHub/AWS hoặc Ruff/full pytest. Không tạo run_id evaluation mới vì chỉ thực thi helper audit.

## Giới hạn
Current baseline source khác code hash của run gốc; không tuyên bố toàn bộ implementation giống run. Các module cần dựng calendar/target/feature khớp. Các kết quả đếm/helpers đã kiểm chứng trên local runtime; không tuyên bố numerical model reproducibility. Không có settlement chính thức độc lập hoặc training sample logs; không gán thiếu dữ liệu thành bug calendar, không suy ảnh hưởng performance. Lịch thư viện/version không là bằng chứng độc lập về settlement. Publication rules không chứng minh historical vintage.
