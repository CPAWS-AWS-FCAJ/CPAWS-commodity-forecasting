\# Fed/EIA NewsLabels Collector — Implementation Plan



\## 1. Mục tiêu



Lập kế hoạch xây dựng collector thu thập tin tức từ nguồn chính thức của Federal Reserve và U.S. Energy Information Administration (EIA), chuẩn hóa metadata, tạo nhãn tác động lên bốn tài sản và ghi kết quả vào bảng `NewsLabels` để chatbot CPAWS sử dụng.



\*\*Phạm vi PR này chỉ là tài liệu kế hoạch.\*\* Không triển khai collector, thay đổi hạ tầng hoặc deploy AWS trong PR này.



\## 2. Phạm vi nguồn dữ liệu



\- \*\*Federal Reserve:\*\* FOMC statements và thông báo chính thức liên quan đến chính sách tiền tệ.

\- \*\*EIA:\*\* Weekly Petroleum Status Report (WPSR) và Today in Energy.



Trước khi đưa nội dung vào pipeline gán nhãn, cần kiểm tra điều khoản sử dụng, quyền lưu trữ và quyền gửi nội dung cho dịch vụ AI bên thứ ba. Chỉ sử dụng nội dung trong phạm vi được phép.



Không đưa toàn bộ bài viết vào DynamoDB. Chỉ lưu tiêu đề, đường dẫn và bản tóm tắt ngắn do nhóm tạo hoặc bước labeling tạo ra. Lưu bản nguồn trên S3 chỉ khi quyền sử dụng và lưu trữ đã được xác nhận.



\## 3. Luồng xử lý dự kiến



1\. Thu thập các thông báo mới từ nguồn chính thức.

2\. Chuẩn hóa URL, tiêu đề, thời điểm xuất bản và thông tin nguồn.

3\. Kiểm tra dữ liệu bắt buộc; loại bỏ URL không hợp lệ hoặc timestamp không thể chuẩn hóa đáng tin cậy.

4\. Tạo bản tóm tắt ngắn, tối đa 600 ký tự.

5\. Kiểm tra quyền sử dụng trước khi gửi tiêu đề và bản tóm tắt sang bước labeling.

6\. Gọi labeling prompt đã được phê duyệt; xác thực kết quả theo JSON Schema hiện hành.

7\. Chuyển kết quả hợp lệ thành một bản ghi cho mỗi tài sản liên quan.

8\. Ghi vào `NewsLabels` theo chính sách idempotency đã được nhóm thống nhất.

9\. Ghi log số lượng bản ghi thu thập, hợp lệ, bị loại, labeling thất bại và ghi DynamoDB thất bại.



Tần suất chạy, cơ chế retry và lịch chạy production sẽ được chốt trong PR triển khai.



\## 4. Hợp đồng dữ liệu



Tuân thủ `docs/api/contract.md`. Bảng `NewsLabels` hiện có partition key `asset` và sort key `sk`.



Bốn giá trị `asset` hợp lệ:



\- `gold`

\- `silver`

\- `brent`

\- `wti`



`sk` có định dạng:



`<published\_at>#<article\_id>`



Ví dụ: `2026-10-13T10:45:00Z#3f9a1c0b7e2d4a61`



Mỗi bản ghi phải có đủ bảy trường:



| Trường | Quy tắc |

|---|---|

| `title` | Chuỗi, tối đa 300 ký tự |

| `summary` | Chuỗi, 1–3 câu, tối đa 600 ký tự |

| `link` | URL HTTP hoặc HTTPS hợp lệ |

| `source` | Tên nguồn, ví dụ `Federal Reserve` hoặc `EIA` |

| `published\_at` | UTC theo định dạng `YYYY-MM-DDTHH:MM:SSZ`, không có phần lẻ giây |

| `impact\_score` | Số nguyên từ 0 đến 3, không lưu dưới dạng chuỗi |

| `direction` | `bullish`, `bearish`, `mixed` hoặc `uncertain` |



`published\_at` phải trùng với phần timestamp đứng trước dấu `#` trong `sk`.



Có thể lưu thêm `article\_id`, `confidence`, `event\_type`, `prompt\_version`, `model\_id`, `fetched\_at` và `labeled\_at` theo nhu cầu truy vết.



Tạo `article\_id` ổn định từ URL chuẩn hóa, chẳng hạn 16 ký tự hex đầu của SHA-256. Nếu một bài liên quan đến nhiều tài sản, tạo một bản ghi cho mỗi tài sản với cùng `article\_id`.



\## 5. Gán nhãn và kiểm soát chất lượng



\- Dùng `docs/prompts/news-labeling-schema.json` làm schema đầu ra; không nhầm schema đầu ra của model với schema lưu DynamoDB.

\- `labeling-v2` là phiên bản hiện có. Chưa coi `labeling-v3` là đã triển khai hoặc được phê duyệt.

\- Trước production, rà soát lỗi của v2, thống nhất phiên bản prompt tiếp theo và benchmark trên 50 bản tin Fed/EIA thực tế có nhãn tham chiếu.

\- Kiểm tra JSON Schema và các quy tắc prompt trước khi cho phép ghi nhãn.

\- Nếu model trả kết quả không hợp lệ sau số lần retry được quy định, đánh dấu thất bại và không sử dụng kết quả đó làm feature dự báo.

\- Khi `relevant=false`, cả bốn tài sản phải có `impact\_score=0`, `direction=uncertain` và `evidence` rỗng.

\- Khi `impact\_score=0`, `direction` phải là `uncertain`.

\- Không gửi `published\_at` hoặc metadata timestamp vào model labeling; ứng dụng quản lý metadata riêng.

\- Nhãn phản ánh nhận định của mô hình về nội dung, không khẳng định bài viết gây ra biến động giá.



\## 6. Idempotency và xử lý bản ghi trùng



Dùng khóa `asset` và `sk` để nhận diện bản ghi. RFC #44 yêu cầu xem xét ghi có điều kiện bằng `attribute\_not\_exists(...)`.



Trước khi triển khai, nhóm cần thống nhất chính sách đối với bài đã tồn tại: bỏ qua bản ghi trùng hay cho phép cập nhật khi nội dung, summary hoặc nhãn được sửa. Chính sách này phải tương thích với hợp đồng hiện hành, trong đó cùng khóa có thể được ghi đè khi xử lý lại bài viết.



Không triển khai hai hành vi mâu thuẫn trong cùng collector. Ghi có điều kiện phải được kiểm thử cho cả lần chạy đầu, lần chạy lặp lại và trường hợp bài viết được sửa.



\## 7. Point-in-time integrity và bảo mật



\- Giữ timestamp gốc và múi giờ nếu cần để truy vết; chuẩn hóa thời điểm lưu trữ sang UTC.

\- Chỉ dùng tin có `published\_at` không muộn hơn thời điểm chốt dự báo.

\- Nếu timestamp thiếu hoặc không đáng tin cậy, không dùng bài đó làm feature theo thời gian nếu chưa có quy tắc xử lý được phê duyệt.

\- Collector có quyền ghi tối thiểu cần thiết; chatbot chỉ cần quyền `Query` đọc dữ liệu.

\- Không ghi nội dung bài viết đầy đủ hoặc thông tin nhạy cảm vào log.

\- Không đưa bí mật AWS hoặc thông tin xác thực vào mã nguồn.



\## 8. Hạ tầng và kiểm thử dự kiến



\- Tận dụng bảng `NewsLabels` và cấu trúc CDK hiện có; không tạo bảng trùng.

\- Kiểm tra các helper IAM liên quan trong `infra/stacks/shared.py`.

\- Chọn cơ chế schedule phù hợp với hạ tầng CDK hiện tại trong PR triển khai.

\- Viết unit test cho chuẩn hóa timestamp, tạo `article\_id`, xác thực schema, lọc URL, ánh xạ tài sản và xử lý bản ghi trùng.

\- Viết test tích hợp cho ghi DynamoDB có điều kiện và đọc dữ liệu qua hợp đồng `get\_news`.

\- Dùng fixture đánh dấu rõ là dữ liệu mẫu khi nguồn thật không khả dụng; không trộn dữ liệu mẫu với dữ liệu thật mà không có nhãn phân biệt.

\- Kiểm tra không rò rỉ dữ liệu tương lai và bảo đảm tương thích với `docs/api/contract.md`.



\## 9. Các bước triển khai tiếp theo



1\. Xác nhận quyền sử dụng nguồn và phạm vi nội dung được phép lưu/gửi cho AI.

2\. Chốt chính sách idempotency và xử lý bài viết được cập nhật.

3\. Chốt lịch chạy và cơ chế retry.

4\. Hoàn thiện, benchmark và phê duyệt prompt labeling trước production.

5\. Triển khai collector và kiểm thử trên môi trường dev.

6\. Xác minh bản ghi thực trong `NewsLabels` và khả năng đọc của chatbot.

7\. Chỉ triển khai theo quy trình review/merge/deploy của nhóm.



\## 10. Tiêu chí hoàn thành



\- Dữ liệu tuân thủ hợp đồng `NewsLabels` hiện hành.

\- Bản ghi hợp lệ có thể được truy vấn theo tài sản và khoảng thời gian.

\- Chạy lặp không tạo bản ghi trùng ngoài chính sách đã thống nhất.

\- Kết quả labeling sai schema không được ghi như dữ liệu hợp lệ.

\- Không dùng thông tin xuất bản sau thời điểm dự báo.

\- Quyền truy cập, điều khoản nguồn và chính sách lưu trữ đã được xác nhận.

\- Test và review hoàn tất trước khi merge/deploy.



