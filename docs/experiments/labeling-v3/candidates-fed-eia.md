# Ứng viên thông cáo Fed/EIA cho bộ kiểm labeling-v3

- File dữ liệu: [`candidates-fed-eia.csv`](candidates-fed-eia.csv) (UTF-8, 69 dòng).
- Mục đích: danh sách để Phước chọn 50 thông cáo thật làm bộ case kiểm labeling-v3 (theo [news-labeling-2026-10.md](../news-labeling-2026-10.md), mục "Việc tiếp theo").
- Trạng thái: **chưa gắn đáp án**. Nhãn `relevant`, `event_type`, `impact_score`, `direction`, `confidence`, `evidence` do Phước gắn tay và chốt cùng ngưỡng trước khi chạy model.
- Lập ngày 27/10/2026.

## Cách chọn

- Chỉ lấy trang chính thức `federalreserve.gov` và `eia.gov`, giai đoạn 01/2025–10/2026.
- Mỗi link đã được mở và đối chiếu tiêu đề, ngày với nội dung trang. Không giữ link nào chưa kiểm được.
- Số liệu tồn kho WPSR lấy từ `csv/table1.csv` trong thư mục lưu trữ của từng kỳ, không lấy qua bên thứ ba.
- Tóm tắt `summary_vi` là lời tự viết, 1–2 câu, không chép đoạn văn gốc. Tiêu đề giữ nguyên tiếng Anh như trang gốc (bài phát biểu có thêm tên người nói trong ngoặc).
- Bỏ các thông cáo đăng trong khoảng 08–21/10/2026, là khoảng ngày của fixture tin giả lập trong `tests/chatbot/`, để tránh nhầm với tin giả lập.
- Không lấy các bài có link hoặc ngày không chắc chắn.

## Cột

| Cột | Nội dung |
|---|---|
| `id` | `F01`–`F34` (Fed), `E01`–`E35` (EIA) |
| `source` | `Fed` hoặc `EIA` |
| `release_type` | Loại thông cáo, xem bảng cơ cấu |
| `title` | Tiêu đề gốc |
| `published_at_utc` | Có giờ (`…T18:00Z`) khi trang hoặc RSS của Fed ghi giờ; chỉ có ngày khi trang không ghi giờ |
| `url` | Link chính thức |
| `summary_vi` | Tóm tắt tự viết |
| `assets_possibly_affected` | Tài sản có thể bị ảnh hưởng (`gold;silver`, `brent;wti`, `-`); chỉ là gợi ý, không phải đáp án |
| `coverage_tag` | Trường hợp mà dòng này giúp phủ, xem bên dưới |
| `selection_reason` | Lý do chọn |

Về giờ đăng:
- Statement FOMC ghi "2:00 p.m. EST/EDT" và được quy về 19:00Z (EST) hoặc 18:00Z (EDT).
- Minutes chỉ có ngày, trừ kỳ 09/2026 có giờ lấy từ RSS của Fed.
- WPSR và thông cáo EIA không ghi giờ trên trang nên chỉ có ngày. Nếu bộ case cần giờ để xử lý giờ chốt giá thì phải kiểm thêm.

## Cơ cấu

| Nguồn | Loại | Số dòng |
|---|---|---|
| Fed | `fomc_statement` (01/2025–09/2026, đủ 14 kỳ) | 14 |
| Fed | `fomc_minutes` | 7 |
| Fed | `speech` | 7 |
| Fed | `testimony` | 1 |
| Fed | `fomc_policy_framework` (cập nhật khung chính sách 22/8/2025) | 1 |
| Fed | `press_release_personnel`, `_enforcement`, `_regulation`, `_orders` | 4 |
| EIA | `wpsr` (Weekly Petroleum Status Report) | 9 |
| EIA | `press_release_forecast` (thông cáo dự báo hằng tháng) | 17 |
| EIA | `press_release_steo` (thông cáo ghi rõ là STEO) | 4 |
| EIA | `aeo_press_release` | 1 |
| EIA | `press_release_admin` | 4 |
| **Tổng** | | **69** (Fed 34, EIA 35) |

| `coverage_tag` | Ý nghĩa | Fed | EIA |
|---|---|---|---|
| `clear_gold_silver` | Tác động rõ lên vàng/bạc (cắt, tăng hoặc báo hiệu đổi lãi suất) | 10 | 0 |
| `clear_oil` | Tác động rõ lên dầu (tồn kho thay đổi lớn, gián đoạn cung có quy mô, dự báo giá đổi mạnh) | 0 | 14 |
| `mixed` | Tín hiệu trái chiều trong cùng thông cáo | 9 | 7 |
| `low_impact` | Liên quan nhưng tác động nhỏ hoặc không bất ngờ | 7 | 3 |
| `title_mismatch` | Tiêu đề nói chủ đề khác (điện, khí, hộ gia đình) nhưng nội dung có dữ liệu về dầu hoặc lãi suất | 1 | 7 |
| `irrelevant` | Gần như không liên quan, ứng viên cho `relevant=false` hoặc impact 0 | 5 | 3 |
| `no_substance` | Tin có vẻ quan trọng nhưng không có nội dung đánh giá được (nhân sự, dữ liệu trễ) | 1 | 1 |
| `uncertain` | Thay đổi khung chính sách, khó xác định hướng | 1 | 0 |

## Ghi chú khi chọn 50

- 14 statement FOMC có cấu trúc gần giống nhau. Nên chọn khoảng 8–10 để giữ đủ các loại giữ, cắt, tăng và phiếu phản đối hai chiều, tránh bộ case nặng về một mẫu văn.
- Giai đoạn 03–07/2026 có xung đột Trung Đông và eo Hormuz. Các thông cáo Fed lúc này nhắc giá năng lượng, phù hợp để kiểm mô hình có tách được tác động lên vàng/bạc và lên dầu.
- EIA không có thông cáo nào tác động rõ lên vàng/bạc. Nếu muốn có ô vàng/bạc khác 0 từ tin dầu (qua kênh lạm phát), Phước cần quyết định có tính hay không khi gắn nhãn.
- Không có thông cáo nào chứa chỉ dẫn kiểu prompt injection. Case injection cho v3 vẫn phải tạo riêng.
- Tóm tắt rỗng: danh sách không có dòng nào như vậy. Nếu v3 cần kiểm quy tắc "tóm tắt rỗng thì 0/uncertain", có thể lấy một dòng bất kỳ rồi để trống tóm tắt khi đưa vào bộ case.

## Chưa có trong danh sách

- Thông cáo về OPEC/OPEC+, IEA OMR và giá kim loại quý: nằm ngoài hai nguồn Fed/EIA nên không lấy.
- Beige Book, Monetary Policy Report bản đầy đủ, Weekly Natural Gas Storage Report, Petroleum Supply Monthly: chưa lấy vì đã đủ khoảng 70 dòng.
- Thông cáo EIA năm 2025 số 565, 568, 572, 578: có trong danh mục nhưng chưa mở để kiểm, nên không đưa vào.
