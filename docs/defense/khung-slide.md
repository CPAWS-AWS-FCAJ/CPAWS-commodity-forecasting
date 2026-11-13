# Khung slide trình bày cuối kỳ

> Bản nháp ngày 13/11/2026. Điều phối: Khải. Mục đích: chia việc làm slide trước 15/11 để mỗi người soạn song song từ chương của mình.
>
> - Thời lượng giả định **15–20 phút trình bày + hỏi đáp**, khoảng 18 slide. `[CHỜ XÁC NHẬN: thời lượng hội đồng FCAJ-AWS quy định]`; nếu ngắn hơn thì gộp theo cột "Gộp khi thiếu giờ".
> - Nội dung slide lấy từ chương đã merge trong `docs/defense/`. Slide không đưa số mới chưa có trong báo cáo.

## Lịch

| Mốc | Việc |
|---|---|
| 15/11 | Chốt khung này: ai làm slide nào |
| 16–21/11 | Mỗi người soạn slide phần mình (trừ số test2020) |
| 22/11 | Đóng băng tính năng: chụp ảnh màn hình web và chatbot bản cuối |
| Trong 2 ngày sau khi chạy test2020 | Long thêm slide kết quả test2020 |
| 23–24/11 | Tập dượt chatbot (Phước) cùng lượt tập slide |
| 25–29/11 | Ghép một file, thống nhất giao diện, tập toàn bộ ít nhất 2 lần |

## Danh sách slide

| # | Slide | Người làm | Nội dung chính | Hình / bằng chứng | Nguồn | Gộp khi thiếu giờ |
|---:|---|---|---|---|---|---|
| 1 | Tiêu đề | Khải | Tên đề tài, nhóm CPAWS, 5 thành viên và vai trò | — | Mở đầu | — |
| 2 | Vấn đề | Khải | 3 khó khăn của người dùng; 4 tài sản; không tư vấn đầu tư | — | Mở đầu, Bối cảnh | Gộp 2 + 3 |
| 3 | Sản phẩm làm được gì | Khải | Khoảng dự báo 1–7 phiên, xác suất tăng, USD/VND, độ tin cậy, chatbot | 1 ảnh trang dự báo (chế độ cơ bản) | Mở đầu, Bài toán | |
| 4 | Mục tiêu và mức đạt | Khải | Bảng 5 mục tiêu: đạt / đạt một phần / đang thu thập | Bảng rút gọn | Mở đầu, Mục tiêu | — |
| 5 | Kiến trúc tổng thể | Tiến | Scheduler → ingest → predict → DynamoDB → API → web; chatbot Bedrock; 5 stack CDK | Sơ đồ kiến trúc hiện trạng (bản cập nhật sau #89) | Ch.4 mục 2–3 | — |
| 6 | Vì sao dự báo return, không dự báo giá | Khải | Ví dụ "chính xác 99% ảo"; 7 phân vị; quy đổi ra khoảng giá | 1 hình minh họa phân vị (không dùng số thật) | Ch.1 mục 1.1 | Gộp 6 + 7 |
| 7 | Dữ liệu | Khải | Nguồn yfinance, lịch giao dịch, chia 2014–2018 / 2019 / 2020→nay, ngày chuyển hợp đồng dầu | Bảng chia tập | Ch.1 mục 1.2 | |
| 8 | Các mô hình đã thử | Khải | Mốc 252 phiên; DLinear, K3, K3b, K4 (13 cấu hình) đều không vượt mốc trên validation 2019 | Bảng 1.4 (pinball skill trung bình) | Ch.1 mục 1.4 | — |
| 9 | Bài học: rò rỉ dữ liệu tương lai | Khải | CEEMDAN + LSTM: R-full đúng chiều 84–86%, R-causal thì không | Hình so sánh R-full / R-causal từ PR #83 (dữ liệu ≤ 2018) | Ch.1 mục 1.4 | Bỏ nếu thiếu giờ, để hỏi đáp |
| 10 | Đánh giá: chỉ số và cách chia | Long | Pinball skill so với mốc, coverage 80%, Brier; vì sao không dùng MAPE/RMSE; test chạy một lần | Sơ đồ walk-forward | Ch.2 mục 2, 5 | Gộp 10 + 11 |
| 11 | Champion / challenger | Long | S1a chạy song song từ 04/11; quy tắc đổi champion (cận dưới CI 95% > 0, có ADR) | Sơ đồ champion/challenger | Ch.1 mục 1.5, Ch.2 mục 3 | |
| 12 | Kết quả test2020 | Long | Kết quả một lượt chạy chính thức, kèm giới hạn; không đổi champion | `[CHỜ SỐ LIỆU: test2020, chỉ sau lần chạy chính thức]` | Ch.2 mục 6 | — |
| 13 | Độ tin cậy trên dữ liệu chạy thật | Long + Tiến | Job `rolling_8w` hằng ngày; web "Đang thu thập (n/20)" hoặc số đo nếu đã đủ 20 | Ảnh khối "Độ tin cậy" chụp ngày 22/11 | Ch.2 Phụ lục A, Ch.4 mục 9 | Gộp vào 11 |
| 14 | Chatbot: thiết kế | Phước | Luồng `POST /chat`, tool `get_forecast` / `get_news`, số chỉ lấy từ tool, không tư vấn | Sơ đồ luồng chat | Ch.3 mục 2, 5, 6 | Gộp 14 + 15 |
| 15 | Chatbot: đánh giá | Phước | Benchmark v2 và v4 chưa đạt, 0 vi phạm chính sách, vì sao giữ v2 | Bảng kết quả v4 (A 5/8, B 17/30) | Ch.3 mục 7 | |
| 16 | Demo trực tiếp | Phước + Tiến | Đăng nhập → trang vàng → đổi VND → hỏi chatbot 2–3 câu theo kịch bản | Web thật; video dự phòng nếu mạng lỗi | `docs/demo/qa-chatbot-final-2026-11-11.md` | Rút còn 1 câu chatbot |
| 17 | Vận hành, bảo mật, chi phí | Tuấn + Tiến | Chạy tự động, alarm, rollback; Cognito, IAM, bảo vệ artifact test; chi phí thực tế so với credit | Bảng chi phí theo dịch vụ | Ch.4, Ch.5 | — |
| 18 | Kết luận và hướng phát triển | Khải | Đạt được gì; giới hạn (chỉ dùng giá, chuỗi đại diện, rủi ro nguồn Yahoo); bước tiếp: tín hiệu ngoài giá, retrain khi có mô hình vượt mốc | — | Ch.1 mục 1.7, Kết luận | — |

Slide dự phòng cho hỏi đáp (không trình bày, mở khi được hỏi): so với proposal (Ch.1 mục 1.6), router chatbot không làm (Ch.3 mục 3), Guardrails không bật (Ch.3, Ch.5), rủi ro Yahoo (Ch.5 mục 6).

## Quy tắc chung

- **Số liệu:** chỉ lấy số đã có trong báo cáo hoặc PR đã merge. Số test2020 chỉ có sau lần chạy chính thức; không vẽ biểu đồ nào trên dữ liệu 2020 → nay trước đó.
- **Chỉ số:** dùng `pinball_skill`, coverage, Brier, `sign_accuracy` kèm `up_rate`; không dùng MAPE, RMSE hay sai số trên mức giá.
- **Cách nói khoảng dự báo:** "khoảng dự báo 80%" là danh nghĩa; không nói "80% khả năng giá nằm trong khoảng". Mức bao phủ thật là `coverage_80`.
- **Vàng, bạc:** luôn ghi "quy đổi từ quỹ GLD/SLV (chuỗi đại diện), không phải giá giao ngay".
- **Ảnh màn hình:** chụp sau đăng nhập; che Account ID (chỉ để 4 số cuối), email và token. Ghi "Mốc thống kê 252 phiên" như trên web.
- **Không tư vấn đầu tư:** không slide nào nói nên mua hay bán.
- **Giao diện:** một template chung do Khải gửi; mỗi slide một ý chính, chữ tối thiểu cỡ 18.
