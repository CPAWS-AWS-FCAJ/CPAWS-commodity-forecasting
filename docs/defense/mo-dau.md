# Mở đầu

> Bản nháp ngày 13/11/2026. Chủ trì: Khải; review: Long, Phước. Cơ sở: `origin/developer` @ `b616185` (13/11/2026).
>
> - Phần này giới thiệu bài toán, mục tiêu, phạm vi và cách đọc báo cáo. Chi tiết kỹ thuật nằm ở 5 chương nội dung, không nhắc lại ở đây.
> - Phần này **không có số của tập test 2020 → nay** và không có số chi phí chốt kỳ. Chỗ để điền ghi `[CHỜ SỐ LIỆU]`.

## Bối cảnh

Giá vàng, bạc và dầu thô biến động mạnh khi có sự kiện lớn: xung đột, quyết định lãi suất của ngân hàng trung ương, quyết định sản lượng của OPEC+. Ở Việt Nam, giá vàng và bạc trong nước bám theo giá thế giới, còn giá dầu thô là căn cứ chính của giá xăng dầu bán lẻ.

Người dùng phổ thông xem được giá hiện tại, nhưng gặp ba khó khăn ([proposal](../proposal/Proposal_final.docx), mục 2):

- **Khó biết sắp tới:** dự báo trên báo chí thường là nhận định định tính, không có con số và không công bố độ chính xác trong quá khứ.
- **Khó hiểu vì sao:** tin tức nhiều, rời rạc, không gắn với con số cụ thể.
- **Khó liên hệ với tiền của mình:** giá thế giới tính bằng USD/ounce hay USD/thùng.

## Bài toán

CPAWS là một website chạy trên AWS. Với mỗi tài sản và mỗi kỳ hạn 1–7 phiên giao dịch tới, website cho biết:

- **khoảng dự báo** (phân vị 10%, 50%, 90%) quy đổi ra khoảng giá, theo USD hoặc VND;
- **xác suất tăng**;
- **độ tin cậy đo trên dữ liệu chạy thật** của chính các dự báo đã phát hành.

Kèm theo là một **chatbot tiếng Việt** trên Amazon Bedrock giải thích dự báo và tin tức liên quan. Chatbot chỉ dùng con số lấy từ hệ thống qua tool, và không tư vấn đầu tư.

Bốn tài sản và chuỗi giá dùng để dự báo:

| Tài sản | Chuỗi dự báo | Ghi chú |
|---|---|---|
| Vàng | GLD (quỹ ETF giữ vàng vật chất) | Chuỗi đại diện, không phải giá giao ngay |
| Bạc | SLV (quỹ ETF giữ bạc vật chất) | Chuỗi đại diện, không phải giá giao ngay |
| Dầu Brent | BZ=F (hợp đồng tương lai gần nhất) | Có bước nhảy ở ngày chuyển hợp đồng |
| Dầu WTI | CL=F (hợp đồng tương lai gần nhất) | Có bước nhảy ở ngày chuyển hợp đồng |

Hệ thống dự báo **phân phối của log return** h phiên tới (h = 1–7) dưới dạng 7 phân vị, không dự báo thẳng mức giá. Lý do: giá ngày mai gần bằng giá hôm nay, nên một mô hình chỉ lặp lại giá hôm nay cũng trông như "chính xác 99%". Dự báo return buộc mô hình học sự thay đổi thật và cho phép đo độ chính xác trung thực (Chương 1, mục 1.1; [ADR-0008](../adr/0008-target-quantiles-evaluation.md)).

## Mục tiêu và mức đạt được

Bảng dưới đối chiếu 5 mục tiêu của proposal với trạng thái ngày 13/11/2026. Chi tiết và bằng chứng nằm ở chương ghi trong cột cuối.

| Mục tiêu (proposal, mục 3) | Trạng thái 13/11/2026 | Chương |
|---|---|---|
| 1. Dự báo phân phối return 1–7 ngày cho 4 tài sản, quy đổi thành khoảng giá và xác suất tăng, cập nhật hằng ngày | **Đạt.** Dự báo phát hành tự động 19:15 thứ Ba–thứ Bảy từ 27/10/2026. Sản phẩm chạy **mốc thống kê 252 phiên** (`baseline-q252`) vì 13 cấu hình mô hình học máy đã thử đều không vượt mốc này trên validation 2019 | 1, 4 |
| 2. Hiển thị chế độ cơ bản và nâng cao; giá theo USD và VND | **Đạt.** Web có hai chế độ và chuyển USD/VND; từ 13/11 có thêm khối quy đổi khoảng dự báo ra số tiền. Phần giải thích theo thành phần CEEMDAN đã bỏ vì không mô hình CEEMDAN nào vào sản phẩm | 1, 4 |
| 3. Chatbot tiếng Việt giải thích dự báo, trích tin tức, từ chối câu ngoài phạm vi | **Đạt một phần.** `POST /chat` chạy trên web với prompt v2, lấy số qua tool `get_forecast` và tin qua `get_news`. Benchmark chính thức của prompt v2 (30/10) và v4 (11/11) đều chưa đạt ngưỡng nhóm đặt ra; không có vi phạm chính sách ở lần chấm tay v4 | 3 |
| 4. Công khai độ chính xác lịch sử trên giao diện | **Đang thu thập.** Job `rolling_8w` chạy hằng ngày từ 12/11; web hiện "Đang thu thập (n/20)" cho tới khi đủ 20 ngày cơ sở, dự kiến cuối tháng 11 | 2, 4 |
| 5. Hệ thống tự vận hành: thu thập, gắn nhãn tin, huấn luyện lại, dự báo | **Đạt một phần.** Thu thập, dự báo và đo độ tin cậy chạy tự động. Huấn luyện lại thay bằng cửa sổ trượt và champion/challenger ([ADR-0011](../adr/0011-weekly-champion-challenger-instead-of-retrain.md)). Gắn nhãn tin vẫn làm tay tới buổi trình bày ([ADR-0013](../adr/0013-manual-news-labels-until-defense.md)) | 1, 3, 4 |

Proposal còn đặt mục tiêu thử nghiệm với 10–15 người dùng thật: buổi dùng thử dự kiến 15–17/11/2026, kết quả `[CHỜ SỐ LIỆU: tổng hợp phản hồi của Tuấn]`.

## Phạm vi

**Trong phạm vi:**

- 4 tài sản ở trên, kỳ hạn 1–7 phiên giao dịch, dự báo theo lô mỗi ngày.
- Một môi trường `dev` trên AWS, region `ap-southeast-1`, hạ tầng viết bằng AWS CDK.
- Web cần đăng nhập Cognito (không tự đăng ký); không có tính năng tải dữ liệu giá.

**Ngoài phạm vi** (proposal mục 4.4, giữ nguyên):

- Khuyến nghị mua bán hoặc tư vấn đầu tư cá nhân.
- Giá xăng dầu bán lẻ và giá vàng miếng trong nước.
- Dự báo trong ngày hoặc giao dịch tự động.
- Fine-tune mô hình ngôn ngữ.
- Lưu hoặc hiển thị toàn văn bài báo. Hệ thống chỉ lưu tiêu đề, tóm tắt do nhóm viết và đường dẫn.

## Nguồn lực

- **Thời gian:** 7 tuần xây dựng, 12/10–29/11/2026; đóng băng tính năng 22/11/2026.
- **Nhóm 5 người:**

| Thành viên | Vai trò | Phụ trách chính |
|---|---|---|
| Trịnh Tiến Khải | Research Lead | Mô hình, dữ liệu, code Lambda predict; điều phối báo cáo |
| Nguyễn Tiến Long | Modeling & Evaluation | Đánh giá, champion/challenger, test2020 |
| Phan Tấn Phước | News & Chatbot | Gắn nhãn tin, chatbot |
| Châu Trần Mạnh Tiến | Platform | CDK, Lambda, web, deploy |
| Huỳnh Ngọc Tuấn | Data & Security Lead | IAM, API Gateway, Cognito, DynamoDB, chi phí |

- **Ngân sách:** khoảng 200 USD credit AWS, Budgets 50 USD/tháng. Chi phí thực tế 12/10–11/11/2026 khoảng 5,28 USD; số chốt kỳ `[CHỜ SỐ LIỆU: Tuấn chốt 30/11]` (Chương 5).

## Nguyên tắc làm việc

Ba nguyên tắc chi phối các quyết định trong báo cáo:

1. **Sản phẩm chạy thật trước.** Mục tiêu là website chạy được trên AWS, không phải bài nghiên cứu. Khi một hướng mô hình không vượt mốc, nhóm giữ mốc trong sản phẩm thay vì đưa mô hình yếu hơn lên.
2. **Chốt kế hoạch trước khi xem kết quả.** Mỗi thí nghiệm có kế hoạch và tiêu chí commit trước khi chạy. Tập test 2020 → nay chỉ chạy một lần sau khi khóa tham số. Benchmark chatbot không sửa prompt rồi chấm lại trên cùng bộ câu.
3. **Không dùng thông tin tương lai.** Train và predict dùng cùng quy tắc thời điểm công bố dữ liệu (`PUBLISHED_AT_RULES`). Phần minh họa CEEMDAN + LSTM ở Chương 1 cho thấy vì sao điều này quan trọng.

## Cấu trúc báo cáo

| Phần | Nội dung | Chủ trì |
|---|---|---|
| [Chương 1. Mô hình và dữ liệu](mo-hinh-va-du-lieu.md) | Target, nguồn dữ liệu, mốc 252 phiên, các mô hình đã thử, champion/challenger, so với proposal | Khải |
| [Chương 2. Phương pháp và kết quả đánh giá](phuong-phap-danh-gia.md) | Chia tập theo thời gian, chỉ số pinball skill và hiệu chỉnh, thống kê, rolling accuracy, kết quả test2020 | Long |
| [Chương 3. Chatbot](chatbot.md) | Luồng `POST /chat`, model Bedrock, tool, lớp chống tư vấn đầu tư, kết quả benchmark | Phước |
| [Chương 4. Triển khai và vận hành](trien-khai-van-hanh.md) | 5 stack CDK, luồng chạy hằng ngày, deploy, rollback, giám sát, web | Tiến |
| [Chương 5. Bảo mật và chi phí](security-and-cost.md) | Quyền truy cập, bảo vệ dữ liệu và artifact, chi phí, rủi ro nguồn dữ liệu | Tuấn |
| Kết luận và phụ lục | Phạm vi hoàn thành, giới hạn, hướng phát triển | Khải biên tập, Long ghép bản cuối |

Quy ước chung:

- Số validation lấy từ ADR và tài liệu thí nghiệm trong repo; số vận hành lấy từ log CloudWatch của các lượt chạy thật.
- Chỉ số chính là `pinball_skill` so với mốc 252 phiên; báo cáo không dùng MAPE, RMSE hay sai số trên mức giá (ADR-0008 mục 5).
- Mọi con số trên web, kể cả khoảng giá quy đổi, là giá trị tham khảo, không phải lời khuyên đầu tư.

## Nguồn

- [Proposal](../proposal/Proposal_final.docx), mục 2–4.
- [Hợp đồng API](../api/contract.md).
- ADR-0005, 0008, 0011, 0013.
- Năm chương nội dung trong `docs/defense/`.
