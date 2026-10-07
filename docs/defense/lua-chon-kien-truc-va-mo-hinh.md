# Tư liệu bảo vệ: vì sao chọn kiến trúc và mô hình

Bản nháp cho phần trình bày trước hội đồng (đầu ra K8). Điền số liệu thật vào cột "Bằng chứng" sau khi có kết quả đánh giá tuần 10. Chi phí và giá dịch vụ cần kiểm tra lại bằng AWS Pricing Calculator trước khi trình bày.

## 1. Kiến trúc hệ thống

| Hạng mục | Lựa chọn | Phương án khác đã cân nhắc | Vì sao chọn | Bằng chứng (điền) |
|---|---|---|---|---|
| Kiểu hệ thống | Serverless, chạy theo lịch (EventBridge Scheduler, Lambda, Step Functions) | EC2 hoặc ECS/EKS chạy 24/7 | Giá cập nhật theo ngày, chỉ cần chạy vài phút mỗi ngày; trả tiền theo lần chạy; không vận hành máy chủ. Riêng control plane EKS khoảng 73 USD/tháng | Chi phí thực tế/tháng |
| Phục vụ dự đoán | Dự đoán theo lô mỗi ngày, lưu sẵn trong DynamoDB | SageMaker real-time endpoint; Serverless Inference | Dự đoán chỉ đổi mỗi ngày; endpoint chạy liên tục tính tiền cả khi không ai dùng | Độ trễ API, chi phí |
| Huấn luyện | SageMaker AI Training Job (CPU) + Model Registry | EC2 tự quản; notebook chạy liên tục; Colab | Chỉ trả tiền khi huấn luyện; lưu phiên bản cho champion/challenger; Colab không tự động theo lịch | Thời gian và chi phí mỗi lần retrain |
| Điều phối | Step Functions | Cron trên EC2; Amazon MWAA | Có retry, xử lý lỗi, sơ đồ trực quan; MWAA tính phí môi trường chạy liên tục | Số lần chạy thành công |
| Lưu trữ | S3 + DynamoDB | RDS; Redshift | Truy vấn theo sản phẩm và ngày; RDS/Redshift tốn chi phí cố định | |
| Chatbot | Bedrock: Converse, tool use, Guardrails, Knowledge Bases | LLM mã nguồn mở trên EC2 GPU; API ngoài AWS; fine-tune | Không thuê GPU; có sẵn Guardrails; số liệu lấy qua tool nên không cần fine-tune | Tỷ lệ từ chối đúng, con số khớp database |
| Model chatbot | Nova Lite (mặc định), Claude Haiku 4.5 (giải thích sâu) | Model lớn cho mọi câu | Câu trả lời dựa trên số liệu có sẵn nên model nhỏ đủ tốt; rẻ hơn nhiều lần | Chi phí mỗi lượt hỏi |
| Kho vector | S3 Vectors | OpenSearch Serverless | OpenSearch Serverless tính phí năng lực tối thiểu theo giờ | |
| Web | Amplify Hosting, API Gateway, Cognito | EC2 web server; Elastic Beanstalk | Web tĩnh + API tự mở rộng, có sẵn đăng nhập và giới hạn lượt gọi | |
| Hạ tầng dạng code | AWS CDK | Tạo tay trên console; Terraform | Tạo lại hoặc xóa toàn bộ bằng một lệnh, tránh bỏ quên tài nguyên tốn tiền | |

## 2. Mô hình dự đoán

| Mô hình | Điểm mạnh | Hạn chế với bài toán này | Vai trò | Kết quả (điền) |
|---|---|---|---|---|
| Naive (return = 0) | Không cần huấn luyện; rất khó thắng với giá theo ngày | Không dự đoán được xu hướng | Mốc tối thiểu | MASE = 1 |
| ARIMA | Cổ điển, nhanh, dễ giải thích | Tuyến tính; phản ứng chậm khi biến động mạnh; khó thêm tín hiệu tin | Mốc so sánh | |
| Prophet | Dễ dùng, tốt cho chuỗi có mùa vụ | Giá vàng, dầu ít mùa vụ; không phản ứng với cú sốc | Không dùng | |
| XGBoost, LightGBM | Mạnh với dữ liệu bảng, nhanh | Phải tự thiết kế nhiều đặc trưng; nhiều ngày cần huấn luyện riêng từng bước | Dự phòng | |
| DLinear | Rất nhẹ, vài phút trên CPU; trên nhiều bộ dữ liệu chuẩn ngang hoặc hơn Transformer | Chỉ học quan hệ tuyến tính | MVP tuần 3–4 | |
| LSTM | Học phi tuyến, nhận thêm tín hiệu | Dễ học thuộc khi chỉ có vài nghìn điểm | Thành phần mô hình kết hợp | |
| CEEMDAN + DLinear/LSTM | Tách xu hướng và dao động ngắn hạn, mỗi phần một mô hình phù hợp → phản ứng nhanh hơn khi biến động mạnh; chatbot giải thích theo thành phần | Tốn tính toán; phải tách theo cửa sổ trượt | **Mô hình chính** | |
| Transformer (PatchTST, Informer) | Mạnh khi dữ liệu lớn | Dễ học thuộc với vài nghìn điểm; cần GPU | Chỉ khi dư thời gian | |
| Chronos (Amazon) | Dự đoán ngay không cần huấn luyện, có trên SageMaker JumpStart | Không đưa được tín hiệu tin; khó giải thích theo thành phần | Mốc so sánh nếu chi phí cho phép | |
| AutoML AWS (Forecast, SageMaker Canvas) | Không cần code | Amazon Forecast ngừng nhận khách hàng mới từ 29/7/2024; Canvas tính phí theo giờ, khó tùy biến | Không dùng | |

## 3. Vì sao dự đoán return thay vì mức giá

Giá ngày mai gần bằng hôm nay: mô hình lặp lại giá hôm nay đã có sai số khoảng 1%, tức "chính xác 99%" ảo. Dự đoán phân vị return buộc mô hình học sự thay đổi thật; quy đổi lại thành khoảng giá và xác suất tăng cho người dùng. Đánh giá bằng MASE so với naive, tỷ lệ đúng chiều, coverage 80%, Brier score (ADR-0002).

## 4. Biểu đồ cần chuẩn bị (skill `forecast-charts`)

- Dải dự đoán quanh COVID 3/2020 và Nga – Ukraine 2/2022: mô hình chính so với DLinear.
- MASE và tỷ lệ đúng chiều theo sản phẩm và chân trời.
- Coverage 80% và biểu đồ độ tin cậy của xác suất tăng.
- Chi phí AWS thực tế theo tuần (Cost Explorer).
