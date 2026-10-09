# EDA giá vàng, bạc, Brent, WTI (10/2026)

- Người làm: Trịnh Tiến Khải (script và bản nháp do Claude Code soạn). Người đọc: Nguyễn Tiến Long, cả nhóm AI.
- Script: `scripts/eda_prices.py` (tái lập: cùng bản clean → cùng số liệu; chạy hai lần cho file giống hệt từng byte).
- Hình và bảng chi tiết: `data/lake/eda/dt=2026-10-09/` (không commit): `rolling_vol_20_2014_2019.png`, `acf_2014_2018.png`, `eda.json`, các file CSV.
- File này chỉ có bảng số tổng hợp, không có chuỗi giá (ADR-0005, chính sách sử dụng dữ liệu).

## Quy ước

- Nguồn và làm sạch theo ADR-0005. Dòng trong `rejected.parquet` không dùng. USD/VND chỉ có trong phần chất lượng dữ liệu.
- Return h phiên: `r_h(t) = ln(P[t+h] / P[t])` qua `src/forecast/returns.horizon_log_returns`, tính trên **lịch phiên riêng** của từng tài sản (vàng, bạc: NYSE; Brent, WTI: CME). Phiên trong lịch mà không có giá thì để NaN, không forward-fill. Giá ≤ 0 (WTI 20/4/2020) cho NaN.
- Cửa sổ gán theo ngày gốc t. Chỉ giữ cửa sổ có cả t và t+h nằm trong giai đoạn, nên cửa sổ 2019 không chạm tới dữ liệu 2020 (cột "vượt khỏi giai đoạn").
- Thống kê phân phối chỉ tính cho **train 2014–2018** và **validation 2019**. Giai đoạn 2020 → nay chỉ có chất lượng dữ liệu; script không tính return của giai đoạn này.
- Với h = 3 và h = 7, các cửa sổ chồng lên nhau nên n không phải số quan sát độc lập.
- Mốc đánh giá: thang MASE = mean|r_h| trên train (MAE của naive return = 0, đúng như `metrics.mase_returns`); Brier của dự báo hằng số p = tỷ lệ tăng trên train; độ phủ trên 2019 của khoảng [q10, q90] lấy từ phân phối train (mốc cho coverage 80%).

## Kết quả

Đầu vào: `clean/prices/dt=2026-10-09` (prices sha256 `21bb22cd5da9…`), chạy dt=2026-10-09.

### Phân phối log return h phiên (đơn vị: %; std, phân vị theo %)

| Tài sản | Giai đoạn | h | n | mean | std | skew | kurt dư | q01 | q10 | q50 | q90 | q99 | tăng | =0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gold | train_2014_2018 | 1 | 1257 | 0.002 | 0.83 | 0.23 | 2.5 | -2.22 | -0.93 | 0.01 | 1.02 | 2.17 | 50.1% | 0.5% |
| gold | train_2014_2018 | 3 | 1255 | 0.004 | 1.38 | 0.11 | 0.6 | -3.17 | -1.59 | -0.05 | 1.75 | 3.54 | 48.4% | 0.1% |
| gold | train_2014_2018 | 7 | 1251 | 0.005 | 2.19 | 0.00 | 0.5 | -5.44 | -2.65 | 0.03 | 2.81 | 5.05 | 50.5% | 0.0% |
| gold | val_2019 | 1 | 251 | 0.065 | 0.74 | -0.01 | 1.1 | -1.79 | -0.85 | 0.09 | 0.87 | 2.03 | 54.6% | 1.2% |
| gold | val_2019 | 3 | 249 | 0.191 | 1.25 | 0.21 | 1.0 | -2.72 | -1.35 | 0.20 | 1.65 | 3.65 | 58.6% | 0.4% |
| gold | val_2019 | 7 | 245 | 0.430 | 1.88 | 0.38 | 0.5 | -3.69 | -1.76 | 0.36 | 2.97 | 5.36 | 59.6% | 0.4% |
| silver | train_2014_2018 | 1 | 1257 | -0.022 | 1.31 | -0.19 | 3.0 | -3.64 | -1.48 | 0.00 | 1.43 | 3.52 | 49.0% | 2.4% |
| silver | train_2014_2018 | 3 | 1255 | -0.070 | 2.26 | 0.19 | 1.6 | -5.65 | -2.68 | -0.07 | 2.62 | 5.96 | 47.3% | 1.7% |
| silver | train_2014_2018 | 7 | 1251 | -0.172 | 3.57 | 0.24 | 0.7 | -8.32 | -4.69 | -0.21 | 4.19 | 9.28 | 46.8% | 1.0% |
| silver | val_2019 | 1 | 251 | 0.054 | 1.21 | -0.32 | 2.9 | -3.41 | -1.38 | 0.07 | 1.31 | 3.40 | 53.4% | 4.4% |
| silver | val_2019 | 3 | 249 | 0.153 | 2.10 | -0.17 | 2.3 | -5.54 | -1.87 | 0.07 | 2.56 | 5.75 | 52.6% | 2.0% |
| silver | val_2019 | 7 | 245 | 0.336 | 3.11 | 0.27 | 1.8 | -6.81 | -2.51 | -0.07 | 4.38 | 8.21 | 47.8% | 1.2% |
| brent | train_2014_2018 | 1 | 1248 | -0.053 | 2.17 | 0.03 | 3.1 | -6.20 | -2.56 | -0.02 | 2.31 | 5.68 | 48.4% | 0.6% |
| brent | train_2014_2018 | 3 | 1246 | -0.175 | 3.57 | 0.32 | 3.1 | -9.51 | -4.28 | -0.11 | 3.75 | 9.91 | 48.2% | 0.4% |
| brent | train_2014_2018 | 7 | 1242 | -0.408 | 5.55 | -0.09 | 1.1 | -14.49 | -7.45 | -0.14 | 6.14 | 14.53 | 49.0% | 0.1% |
| brent | val_2019 | 1 | 251 | 0.073 | 1.98 | 0.68 | 9.4 | -4.91 | -2.26 | 0.27 | 1.98 | 4.44 | 57.4% | 0.8% |
| brent | val_2019 | 3 | 249 | 0.226 | 3.17 | -0.46 | 1.9 | -8.47 | -3.63 | 0.53 | 3.84 | 7.01 | 59.4% | 0.0% |
| brent | val_2019 | 7 | 245 | 0.414 | 4.32 | -0.90 | 1.4 | -12.49 | -5.11 | 1.09 | 4.70 | 8.69 | 64.5% | 0.0% |
| wti | train_2014_2018 | 1 | 1252 | -0.056 | 2.29 | 0.07 | 2.6 | -6.01 | -2.79 | 0.03 | 2.44 | 6.04 | 50.6% | 0.2% |
| wti | train_2014_2018 | 3 | 1250 | -0.179 | 3.79 | 0.25 | 2.8 | -9.81 | -4.62 | -0.16 | 4.06 | 9.20 | 48.0% | 0.2% |
| wti | train_2014_2018 | 7 | 1246 | -0.419 | 5.83 | -0.12 | 0.9 | -14.96 | -8.04 | -0.04 | 6.12 | 15.00 | 49.4% | 0.2% |
| wti | val_2019 | 1 | 251 | 0.108 | 2.13 | 0.53 | 7.2 | -5.72 | -2.31 | 0.21 | 2.41 | 4.73 | 55.4% | 0.4% |
| wti | val_2019 | 3 | 249 | 0.319 | 3.41 | -0.13 | 0.8 | -8.58 | -3.94 | 0.47 | 4.20 | 8.52 | 57.0% | 0.0% |
| wti | val_2019 | 7 | 245 | 0.622 | 4.70 | -0.60 | 1.0 | -12.23 | -6.10 | 1.21 | 6.00 | 10.74 | 61.6% | 0.4% |

### Cửa sổ NaN theo lý do (số cửa sổ có ngày gốc trong giai đoạn)

| Tài sản | Giai đoạn | h | tổng cửa sổ | NaN | missing_session | rejected_row | negative_price | vượt khỏi giai đoạn |
|---|---|---|---|---|---|---|---|---|
| gold | train_2014_2018 | 1 | 1258 | 0 | 0 | 0 | 0 | 1 |
| gold | train_2014_2018 | 3 | 1258 | 0 | 0 | 0 | 0 | 3 |
| gold | train_2014_2018 | 7 | 1258 | 0 | 0 | 0 | 0 | 7 |
| gold | val_2019 | 1 | 252 | 0 | 0 | 0 | 0 | 1 |
| gold | val_2019 | 3 | 252 | 0 | 0 | 0 | 0 | 3 |
| gold | val_2019 | 7 | 252 | 0 | 0 | 0 | 0 | 7 |
| silver | train_2014_2018 | 1 | 1258 | 0 | 0 | 0 | 0 | 1 |
| silver | train_2014_2018 | 3 | 1258 | 0 | 0 | 0 | 0 | 3 |
| silver | train_2014_2018 | 7 | 1258 | 0 | 0 | 0 | 0 | 7 |
| silver | val_2019 | 1 | 252 | 0 | 0 | 0 | 0 | 1 |
| silver | val_2019 | 3 | 252 | 0 | 0 | 0 | 0 | 3 |
| silver | val_2019 | 7 | 252 | 0 | 0 | 0 | 0 | 7 |
| brent | train_2014_2018 | 1 | 1259 | 10 | 10 | 0 | 0 | 1 |
| brent | train_2014_2018 | 3 | 1259 | 10 | 10 | 0 | 0 | 3 |
| brent | train_2014_2018 | 7 | 1259 | 10 | 10 | 0 | 0 | 7 |
| brent | val_2019 | 1 | 252 | 0 | 0 | 0 | 0 | 1 |
| brent | val_2019 | 3 | 252 | 0 | 0 | 0 | 0 | 3 |
| brent | val_2019 | 7 | 252 | 0 | 0 | 0 | 0 | 7 |
| wti | train_2014_2018 | 1 | 1259 | 6 | 6 | 0 | 0 | 1 |
| wti | train_2014_2018 | 3 | 1259 | 6 | 6 | 0 | 0 | 3 |
| wti | train_2014_2018 | 7 | 1259 | 6 | 6 | 0 | 0 | 7 |
| wti | val_2019 | 1 | 252 | 0 | 0 | 0 | 0 | 1 |
| wti | val_2019 | 3 | 252 | 0 | 0 | 0 | 0 | 3 |
| wti | val_2019 | 7 | 252 | 0 | 0 | 0 | 0 | 7 |

### Mốc cho đánh giá (train 2014–2018 → validation 2019)

| Tài sản | h | thang MASE = mean\|r\| train | naive MAE 2019 | naive MASE 2019 | tăng train | tăng 2019 | Brier 2019, p = tỷ lệ tăng train | đúng chiều 2019, đoán theo đa số train | q10 / q90 train (%) | coverage 2019 của [q10, q90] train |
|---|---|---|---|---|---|---|---|---|---|---|
| gold | 1 | 0.610% | 0.557% | 0.91 | 50.1% | 54.6% | 0.2499 | 54.6% | -0.93 / 1.02 | 86.1% |
| gold | 3 | 1.070% | 0.951% | 0.89 | 48.4% | 58.6% | 0.2531 | 41.4% | -1.59 / 1.75 | 84.7% |
| gold | 7 | 1.716% | 1.441% | 0.84 | 50.5% | 59.6% | 0.2490 | 59.6% | -2.65 / 2.81 | 84.5% |
| silver | 1 | 0.939% | 0.844% | 0.90 | 49.0% | 53.4% | 0.2508 | 46.6% | -1.48 / 1.43 | 82.5% |
| silver | 3 | 1.687% | 1.496% | 0.89 | 47.3% | 52.6% | 0.2522 | 47.4% | -2.68 / 2.62 | 83.1% |
| silver | 7 | 2.754% | 2.276% | 0.83 | 46.8% | 47.8% | 0.2496 | 52.2% | -4.69 / 4.19 | 83.7% |
| brent | 1 | 1.503% | 1.361% | 0.91 | 48.4% | 57.4% | 0.2526 | 42.6% | -2.56 / 2.31 | 84.5% |
| brent | 3 | 2.617% | 2.357% | 0.90 | 48.2% | 59.4% | 0.2538 | 40.6% | -4.28 / 3.75 | 80.3% |
| brent | 7 | 4.150% | 3.306% | 0.80 | 49.0% | 64.5% | 0.2529 | 35.5% | -7.45 / 6.14 | 89.4% |
| wti | 1 | 1.654% | 1.487% | 0.90 | 50.6% | 55.4% | 0.2494 | 55.4% | -2.79 / 2.44 | 82.5% |
| wti | 3 | 2.820% | 2.623% | 0.93 | 48.0% | 57.0% | 0.2532 | 43.0% | -4.62 / 4.06 | 81.9% |
| wti | 7 | 4.430% | 3.624% | 0.82 | 49.4% | 61.6% | 0.2513 | 38.4% | -8.04 / 6.12 | 85.3% |

### ACF return ngày, 2014–2018 (lag 1–20)

| Tài sản | chuỗi | lag1 | lag2 | lag5 | lag10 | lag20 | số lag ngoài ±1,96/√n | band |
|---|---|---|---|---|---|---|---|---|
| gold | r | -0.057 | -0.014 | 0.003 | -0.052 | -0.064 | 2/20 | 0.055 |
| gold | \|r\| | 0.008 | 0.069 | 0.102 | 0.103 | 0.062 | 17/20 | 0.055 |
| silver | r | -0.002 | -0.007 | -0.000 | -0.049 | -0.050 | 2/20 | 0.055 |
| silver | \|r\| | 0.072 | -0.009 | 0.022 | 0.045 | 0.086 | 5/20 | 0.055 |
| brent | r | -0.115 | 0.095 | 0.016 | 0.045 | 0.016 | 3/20 | 0.055 |
| brent | \|r\| | 0.207 | 0.216 | 0.213 | 0.170 | 0.145 | 20/20 | 0.055 |
| wti | r | -0.098 | 0.061 | 0.037 | -0.009 | 0.028 | 2/20 | 0.055 |
| wti | \|r\| | 0.270 | 0.247 | 0.246 | 0.209 | 0.150 | 20/20 | 0.055 |

### Tương quan return 1 ngày giữa các tài sản (ngày chung)

**train_2014_2018** (n ngày chung theo cặp: 1248)

| | gold | silver | brent | wti |
|---|---|---|---|---|
| gold | 1.00 | 0.79 | 0.07 | 0.07 |
| silver | 0.79 | 1.00 | 0.17 | 0.20 |
| brent | 0.07 | 0.17 | 1.00 | 0.88 |
| wti | 0.07 | 0.20 | 0.88 | 1.00 |

**val_2019** (n ngày chung theo cặp: 251)

| | gold | silver | brent | wti |
|---|---|---|---|---|
| gold | 1.00 | 0.79 | -0.14 | -0.13 |
| silver | 0.79 | 1.00 | -0.05 | -0.03 |
| brent | -0.14 | -0.05 | 1.00 | 0.92 |
| wti | -0.13 | -0.03 | 0.92 | 1.00 |

### Số ngày tài sản hàng có phiên mà tài sản cột không có

**train_2014_2018**

| có \ không có | gold | silver | brent | wti |
|---|---|---|---|---|
| gold | 0 | 0 | 4 | 2 |
| silver | 0 | 0 | 4 | 2 |
| brent | 0 | 0 | 0 | 0 |
| wti | 0 | 0 | 2 | 0 |

**val_2019**

| có \ không có | gold | silver | brent | wti |
|---|---|---|---|---|
| gold | 0 | 0 | 0 | 0 |
| silver | 0 | 0 | 0 | 0 |
| brent | 0 | 0 | 0 | 0 |
| wti | 0 | 0 | 0 | 0 |

### Chất lượng dữ liệu theo năm, 2012 → nay (mọi giai đoạn)

Phiên thiếu = phiên trong lịch sàn mà prices.parquet không có (trong ngoặc: do dòng bị loại). Lịch: gold/silver NYSE, wti/brent CME, usd_vnd thứ Hai–thứ Sáu.

**gold**

| năm | phiên lịch | dòng giữ | thiếu (loại) | ngoài lịch |
|---|---|---|---|---|
| 2012 | 250 | 250 | 0 (0) | 0 |
| 2013 | 252 | 252 | 0 (0) | 0 |
| 2014 | 252 | 252 | 0 (0) | 0 |
| 2015 | 252 | 252 | 0 (0) | 0 |
| 2016 | 252 | 252 | 0 (0) | 0 |
| 2017 | 251 | 251 | 0 (0) | 0 |
| 2018 | 251 | 251 | 0 (0) | 0 |
| 2019 | 252 | 252 | 0 (0) | 0 |
| 2020 | 253 | 253 | 0 (0) | 0 |
| 2021 | 252 | 252 | 0 (0) | 0 |
| 2022 | 251 | 251 | 0 (0) | 0 |
| 2023 | 250 | 250 | 0 (0) | 0 |
| 2024 | 252 | 252 | 0 (0) | 0 |
| 2025 | 250 | 250 | 0 (0) | 0 |
| 2026 | 193 | 193 | 0 (0) | 0 |

**silver**

| năm | phiên lịch | dòng giữ | thiếu (loại) | ngoài lịch | kept:jump | kept:stale |
|---|---|---|---|---|---|---|
| 2012 | 250 | 250 | 0 (0) | 0 | 0 | 0 |
| 2013 | 252 | 252 | 0 (0) | 0 | 0 | 0 |
| 2014 | 252 | 252 | 0 (0) | 0 | 0 | 1 |
| 2015 | 252 | 252 | 0 (0) | 0 | 0 | 0 |
| 2016 | 252 | 252 | 0 (0) | 0 | 0 | 0 |
| 2017 | 251 | 251 | 0 (0) | 0 | 0 | 0 |
| 2018 | 251 | 251 | 0 (0) | 0 | 0 | 1 |
| 2019 | 252 | 252 | 0 (0) | 0 | 0 | 0 |
| 2020 | 253 | 253 | 0 (0) | 0 | 1 | 2 |
| 2021 | 252 | 252 | 0 (0) | 0 | 0 | 0 |
| 2022 | 251 | 251 | 0 (0) | 0 | 0 | 0 |
| 2023 | 250 | 250 | 0 (0) | 0 | 0 | 0 |
| 2024 | 252 | 252 | 0 (0) | 0 | 0 | 0 |
| 2025 | 250 | 250 | 0 (0) | 0 | 0 | 0 |
| 2026 | 193 | 193 | 0 (0) | 0 | 1 | 0 |

**brent**

| năm | phiên lịch | dòng giữ | thiếu (loại) | ngoài lịch | kept:low_liquidity | kept:roll | kept:stale | kept:xcheck_resid | rej:exchange_holiday |
|---|---|---|---|---|---|---|---|---|---|
| 2012 | 252 | 243 | 9 (0) | 0 | 4 | 12 | 0 | 0 | 0 |
| 2013 | 252 | 243 | 9 (0) | 0 | 16 | 12 | 1 | 0 | 0 |
| 2014 | 252 | 250 | 2 (0) | 0 | 13 | 12 | 0 | 0 | 0 |
| 2015 | 252 | 252 | 0 (0) | 0 | 12 | 12 | 0 | 0 | 0 |
| 2016 | 252 | 250 | 2 (0) | 0 | 14 | 12 | 0 | 0 | 0 |
| 2017 | 251 | 251 | 0 (0) | 0 | 9 | 12 | 0 | 0 | 0 |
| 2018 | 252 | 251 | 1 (0) | 0 | 6 | 12 | 0 | 0 | 0 |
| 2019 | 252 | 252 | 0 (0) | 0 | 2 | 12 | 0 | 0 | 0 |
| 2020 | 253 | 253 | 0 (0) | 0 | 3 | 12 | 0 | 10 | 0 |
| 2021 | 252 | 252 | 0 (0) | 0 | 2 | 12 | 0 | 0 | 0 |
| 2022 | 251 | 251 | 0 (0) | 0 | 0 | 12 | 0 | 0 | 0 |
| 2023 | 250 | 250 | 0 (0) | 0 | 1 | 12 | 0 | 0 | 1 |
| 2024 | 252 | 252 | 0 (0) | 0 | 0 | 12 | 0 | 0 | 0 |
| 2025 | 251 | 251 | 0 (0) | 0 | 0 | 12 | 0 | 0 | 1 |
| 2026 | 193 | 193 | 0 (0) | 0 | 0 | 10 | 0 | 1 | 0 |

**wti**

| năm | phiên lịch | dòng giữ | thiếu (loại) | ngoài lịch | kept:low_liquidity | kept:negative_price | kept:roll | kept:xcheck_level | rej:exchange_holiday |
|---|---|---|---|---|---|---|---|---|---|
| 2012 | 252 | 250 | 2 (0) | 0 | 0 | 0 | 12 | 0 | 0 |
| 2013 | 252 | 252 | 0 (0) | 0 | 1 | 0 | 12 | 0 | 0 |
| 2014 | 252 | 252 | 0 (0) | 0 | 2 | 0 | 12 | 3 | 0 |
| 2015 | 252 | 252 | 0 (0) | 0 | 1 | 0 | 12 | 5 | 0 |
| 2016 | 252 | 250 | 2 (0) | 0 | 0 | 0 | 12 | 16 | 0 |
| 2017 | 251 | 251 | 0 (0) | 0 | 0 | 0 | 12 | 0 | 0 |
| 2018 | 252 | 251 | 1 (0) | 0 | 0 | 0 | 12 | 3 | 0 |
| 2019 | 252 | 252 | 0 (0) | 0 | 1 | 0 | 12 | 1 | 0 |
| 2020 | 253 | 253 | 0 (0) | 0 | 4 | 1 | 12 | 10 | 0 |
| 2021 | 252 | 252 | 0 (0) | 0 | 3 | 0 | 12 | 0 | 0 |
| 2022 | 251 | 251 | 0 (0) | 0 | 1 | 0 | 12 | 8 | 0 |
| 2023 | 250 | 250 | 0 (0) | 0 | 2 | 0 | 12 | 0 | 0 |
| 2024 | 252 | 252 | 0 (0) | 0 | 0 | 0 | 12 | 1 | 0 |
| 2025 | 251 | 251 | 0 (0) | 0 | 1 | 0 | 12 | 0 | 1 |
| 2026 | 193 | 193 | 0 (0) | 0 | 0 | 0 | 9 | 47 | 0 |

**usd_vnd**

| năm | phiên lịch | dòng giữ | thiếu (loại) | ngoài lịch | kept:jump | kept:stale | rej:bad_value | rej:spike |
|---|---|---|---|---|---|---|---|---|
| 2012 | 261 | 258 | 3 (3) | 0 | 0 | 2 | 3 | 2 |
| 2013 | 261 | 260 | 1 (1) | 0 | 1 | 80 | 1 | 0 |
| 2014 | 261 | 257 | 4 (4) | 0 | 0 | 7 | 4 | 0 |
| 2015 | 261 | 258 | 3 (3) | 0 | 0 | 6 | 3 | 3 |
| 2016 | 261 | 261 | 0 (0) | 0 | 0 | 0 | 0 | 0 |
| 2017 | 260 | 260 | 0 (0) | 0 | 2 | 0 | 0 | 0 |
| 2018 | 261 | 259 | 2 (2) | 0 | 0 | 0 | 2 | 2 |
| 2019 | 261 | 257 | 4 (3) | 0 | 0 | 146 | 3 | 3 |
| 2020 | 262 | 261 | 1 (1) | 0 | 1 | 107 | 1 | 1 |
| 2021 | 261 | 260 | 1 (1) | 0 | 0 | 12 | 1 | 1 |
| 2022 | 260 | 260 | 0 (0) | 0 | 0 | 7 | 0 | 0 |
| 2023 | 260 | 260 | 0 (0) | 0 | 0 | 13 | 0 | 0 |
| 2024 | 262 | 262 | 0 (0) | 0 | 0 | 10 | 0 | 0 |
| 2025 | 261 | 257 | 4 (0) | 0 | 0 | 8 | 0 | 0 |
| 2026 | 201 | 200 | 1 (0) | 0 | 0 | 8 | 0 | 0 |

### Quanh 20/4/2020 (không ghi giá)

| ngày | wti: trạng thái / flag | brent: trạng thái / flag |
|---|---|---|
| 2020-04-14 | ok / - | ok / - |
| 2020-04-15 | ok / - | ok / - |
| 2020-04-16 | ok / - | ok / - |
| 2020-04-17 | ok / - | ok / xcheck_resid |
| 2020-04-20 | negative / negative_price | ok / - |
| 2020-04-21 | ok / xcheck_level | ok / xcheck_resid |
| 2020-04-22 | ok / roll | ok / xcheck_resid |
| 2020-04-23 | ok / xcheck_level | ok / xcheck_resid |
| 2020-04-24 | ok / xcheck_level | ok / - |
| 2020-04-27 | ok / xcheck_level | ok / xcheck_resid |
| 2020-04-28 | ok / - | ok / - |

Cửa sổ WTI thành NaN vì giá âm 20/4/2020: h1 = 2, h3 = 2, h7 = 2 (ngày 20/4 là gốc hoặc đích của cửa sổ).

## Nhận xét cho thiết kế mô hình (chỉ dựa trên 2014–2019)

1. **Đuôi dày vừa phải, giảm dần khi h tăng.** Với h = 1 trên train, kurtosis dư là 2,5–3,1 cho cả bốn tài sản; q01 và q99 nằm khoảng 2,6–2,9 std, so với 2,33 của phân phối chuẩn. Năm 2019, Brent (9,4) và WTI (7,2) có đuôi dày hơn hẳn vì một vài phiên cực đoan. Đến h = 7, kurtosis dư còn 0,5–1,1. → Dùng quantile loss (không giả định phân phối chuẩn) là hợp lý. Phân vị 10/90 ít bị đuôi ảnh hưởng, nhưng khoảng cho h = 1 của dầu cần thêm ví dụ biến động mạnh khi đánh giá.
2. **Return gần như không tự tương quan, còn độ lớn thì có (biến động theo cụm).** ACF của r chỉ có 2–3/20 lag vượt dải ±1,96/√n. Ngược lại, ACF của |r| vượt dải ở 20/20 lag với dầu (0,15–0,27) và 17/20 lag với vàng (0,06–0,10). Bạc yếu hơn (5/20). → Khó thắng naive ở trung vị (MASE gần 1 là bình thường). Phần mô hình có thể làm tốt hơn là **độ rộng khoảng theo biến động gần đây**. Đây cũng là chỗ để các IMF tần số cao của CEEMDAN và đặc trưng biến động trượt phát huy tác dụng.
3. **2019 khác train cả về mức biến động lẫn xu hướng.** Std h = 1 năm 2019 thấp hơn train (vàng 0,74% so với 0,83%; dầu 1,98–2,13% so với 2,17–2,29%). Tỷ lệ tăng năm 2019 phần lớn là 53–65% (riêng bạc h = 7 là 47,8%), trong khi train chỉ 47–51%. Vì vậy khoảng [q10, q90] cố định lấy từ train phủ 80–89% trên 2019 thay vì 80%, tức là quá rộng. Thang MASE lấy từ train cũng làm naive có MASE 0,80–0,93 trên 2019. → Trên validation phải so mô hình **với naive trên cùng giai đoạn**, không so với mốc 1,00. Coverage cần báo theo từng giai đoạn biến động. Khoảng tĩnh không thích nghi được khi biến động đổi chế độ.
4. **Mốc chiều và Brier không ổn định.** Trên train, tỷ lệ tăng xấp xỉ 50%, nên Brier của p hằng số trên 2019 là 0,249–0,254, gần như bằng 0,25. Dự báo "theo chiều đa số của train" chỉ đúng chiều 35–60% trên 2019. Một mô hình luôn đoán "tăng" sẽ đúng chiều 57–65% với dầu ở h = 3 và h = 7 năm 2019. → Báo tỷ lệ đúng chiều luôn kèm **tỷ lệ tăng thực tế** của giai đoạn đó. Đặt mốc Brier ở 0,25, đồng thời kiểm tra mô hình không chỉ học drift của train (train dầu có mean âm do giai đoạn sụt giá 2014–2015).
5. **Hai cặp tài sản gần như tách rời nhau.** Tương quan return 1 ngày giữa vàng và bạc là 0,79 (cả train và 2019), giữa Brent và WTI là 0,88 (train) và 0,92 (2019). Giữa kim loại và dầu chỉ khoảng 0,07 (train) và −0,14 đến −0,03 (2019). → Mô hình chung hoặc đặc trưng chéo nên giới hạn trong từng cặp (kim loại, dầu). Đưa return dầu vào mô hình kim loại không có cơ sở ở tần suất ngày. Khi ghép các tài sản về một lịch, nhớ GLD/SLV chốt lúc 16:00 ET còn dầu chốt lúc 14:30 ET.
6. **Brent (BZ=F) 2014–2018 nhiễu hơn WTI.** Brent thiếu 5 phiên CME trong 2014–2018, làm mất 10 cửa sổ cho mỗi h (WTI thiếu 3 phiên, mất 6 cửa sổ). Ngoài ra Brent có 6–14 phiên `low_liquidity` mỗi năm. ACF của return Brent dao động ở lag 1 và 2 (−0,115 rồi +0,095), mạnh hơn WTI (−0,098 rồi +0,061), khớp với hiện tượng giá đóng cửa nhiễu do ít giao dịch. → Cần ablation dùng WTI (hoặc chênh lệch Brent−WTI) làm đầu vào phụ cho Brent. Với Brent, dùng phần dư `xcheck_resid` làm cờ chất lượng, không dùng làm đặc trưng.
7. **Kim loại có nhiều return bằng 0 hơn dầu.** Bạc có 2,4% (train) và 4,4% (2019) số phiên có r_1 = 0, vì SLV giá thấp nên bước giá 0,01 USD là đáng kể. Vàng chỉ có 0,5–1,2%. → Khi tính xác suất tăng và Brier, quy ước r = 0 là "không tăng" (như `metrics.brier_score`). Cần ghi rõ quy ước này trong báo cáo.

## Ghi chú chất lượng dữ liệu (mọi giai đoạn, không phải thống kê return)

- Vàng và bạc không thiếu phiên NYSE nào từ 2012 → nay.
- Brent thiếu 9 phiên mỗi năm trong 2012–2013. Đây là các phiên ngay sau ngày đáo hạn theo lịch ICE cũ (ADR-0005), nằm trong giai đoạn khởi động CEEMDAN.
- USD/VND có nhiều dòng `stale` năm 2013 (80), 2019 (146) và 2020 (107). Chuỗi này chỉ dùng hiển thị.
- WTI năm 2026 có 47 dòng `xcheck_level` (lệch > 3% so với RWTC). Đây là cờ đối chiếu với EIA, chưa rõ do thị trường hay do nguồn; cần xem riêng (đã ghi vào việc phát sinh). Đây là dữ liệu giai đoạn test nên không được dùng để định hướng thiết kế.
