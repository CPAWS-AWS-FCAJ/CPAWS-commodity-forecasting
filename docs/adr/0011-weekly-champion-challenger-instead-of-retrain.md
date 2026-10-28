# ADR-0011: Chấm champion/challenger hằng tuần thay cho retrain bằng SageMaker AI

- Ngày: 2026-10-28
- Trạng thái: Đã chấp nhận
- Người viết: Trịnh Tiến Khải (bản nháp do Claude soạn); người duyệt: Nguyễn Tiến Long, Châu Trần Mạnh Tiến

## Bối cảnh

Proposal và `deployment-plan.md` (giai đoạn 6) đặt "retrain hằng tuần" là mục Must: Step Functions → SageMaker AI Training Job → Model Registry → so champion/challenger, hạn demo 8/11.

Tình hình ngày 28/10:
- Production dùng `baseline-q252` (phân vị thực nghiệm 252 phiên nhân quả). Mô hình này không có tham số để train; cửa sổ 252 phiên đã tự trượt mỗi ngày trong Lambda predict.
- DLinear MVP, K3 (CEEMDAN + DLinear) và K3b đều không đạt tiêu chí lên production (ADR-0008, ADR-0009, ADR-0010). Challenger hiện tại là S1a, cũng không cần train và chỉ cần NumPy.
- Chưa ai bắt đầu giai đoạn 6. Còn 25 ngày tới đóng băng 22/11; web, chatbot và tin tức đang chậm hơn lịch.

Dựng pipeline SageMaker lúc này là xây hạ tầng cho một mô hình không tồn tại.

## Các phương án

1. **Giữ kế hoạch: Step Functions + SageMaker AI Training Job + Model Registry.** Đúng chữ trong proposal. Nhưng không có mô hình nào cần train; tốn khoảng 5 điểm việc của Tiến (10 giờ) đúng lúc web cần người; thêm quyền IAM cho SageMaker; chi phí Training Job nhỏ nhưng khác 0.
2. **Retrain DLinear hằng tuần cho có.** Có pipeline chạy thật, nhưng huấn luyện lại một mô hình đã biết là kém mốc ở 28/28 nhóm, kết quả không dùng vào đâu.
3. **Chấm champion/challenger hằng tuần trên dữ liệu chạy thật, không train.** Mô hình cập nhật hằng ngày theo cửa sổ trượt (đã có). Thêm: predict tính S1a song song (shadow) và ghi S3; job đo độ tin cậy hằng tuần chấm cả champion và challenger trên cùng các cặp dự báo–thực tế. Không thêm dịch vụ AWS mới, chi phí gần 0.

## Quyết định

Chọn **phương án 3**. Bỏ giai đoạn 6 của `deployment-plan.md` (Step Functions, SageMaker AI Training Job, Model Registry) khỏi phạm vi trước buổi bảo vệ.

1. **Cập nhật mô hình:** `baseline-q252` và S1a dùng cửa sổ trượt nhân quả, tự cập nhật mỗi ngày giao dịch trong Lambda predict. Đây là cách "huấn luyện lại" của hai mô hình không có tham số học.
2. **Challenger chạy song song:** Lambda predict tính S1a cùng lúc với champion, ghi S3 `eval/shadow/<model_version>/dt=<ngày>/`. Không ghi DynamoDB `Forecasts`, không đổi `contract.md`, người dùng không thấy.
3. **So sánh hằng tuần:** job đo độ tin cậy (`rolling_8w`, RFC #45) chấm cả champion và challenger trên cùng tập cặp đã có nhãn, lưu `pinball_skill`, `coverage_80`, `width_80` của từng mô hình. Chỉ để báo cáo và cho buổi bảo vệ.
4. **Đổi champion vẫn theo ADR-0008 và ADR-0009 mục 4** (cận dưới CI 95% của `pinball_skill` trung bình 7 h > 0 trên tập đánh giá đã chốt). Vài tuần dữ liệu chạy thật không đủ để kết luận, nên không tự động đổi champion; mọi lần đổi phải có ADR.
5. **Nếu sau này có mô hình cần train** (ví dụ K4 dùng tín hiệu OVX/GVZ): train ở máy hoặc Kaggle, đóng gói artifact theo định dạng `models/<asset>/<model_version>/` đã có, predict đọc từ S3. Không dựng SageMaker trước 22/11.

## Hệ quả

- **Dễ hơn:** Tiến dồn thời gian giai đoạn 6 sang web và Amplify; không cần quyền IAM cho SageMaker và Step Functions; giữ credit.
- **Khó hơn:** mục Must "retrain hằng tuần" trong proposal được hiểu lại thành "mô hình tự cập nhật hằng ngày + so champion/challenger hằng tuần tự động". Báo cáo cuối và slide phải nói rõ lý do bằng kết quả ADR-0009/0010, không để người nghe tưởng thiếu tính năng.
- **Việc kéo theo:**
  - Khải: thêm nhánh shadow S1a trong predict (cần Tiến review).
  - Long: job `rolling_8w` nhận nhiều `model_version`, đọc champion từ DynamoDB và challenger từ S3 `eval/shadow/`.
  - Tuấn: quyền ghi `eval/shadow/` cho role của Lambda predict.
  - Cập nhật `deployment-plan.md` (giai đoạn 6) và `tasks.md` (việc tuần 3–5 của Tiến, Khải, Long liên quan retrain).
- **Rủi ro cần theo dõi:** shadow làm Lambda predict chạy lâu hơn. S1a chỉ là vài phép NumPy trên 252 phiên, ước tính thêm dưới 1 giây; vẫn kiểm `Duration` trong CloudWatch sau lần deploy đầu.
