# Kế hoạch triển khai Fed/EIA NewsLabels Collector

**Trạng thái:** Tài liệu kế hoạch triển khai
**Môi trường:** `cpaws-dev`
**Thành phần liên quan:** S3, DynamoDB `NewsLabels`, chatbot News Retrieval
**Phạm vi:** Thu thập tin tức Fed/EIA chính thức, quy trình gán nhãn thủ công, xác thực và ghi dữ liệu.

---

## 1. Mục tiêu và phạm vi

Mục tiêu của dự án là xây dựng một collector có khả năng thu thập metadata tin tức chính thức từ Federal Reserve và U.S. Energy Information Administration (EIA), chuẩn bị dữ liệu cho quy trình gán nhãn thủ công, xác thực nhãn đã hoàn thiện và ghi các bản ghi hợp lệ vào bảng DynamoDB `NewsLabels` hiện có.

Quy trình được tách biệt giữa thu thập tin tức và gán nhãn:

- Collector tìm kiếm và chuẩn hóa metadata tin tức chính thức từ Fed/EIA.
- Metadata sau khi thu thập được lưu trong S3 với prefix `pending/`.
- Phước trực tiếp thực hiện tóm tắt và gán nhãn thủ công.
- File nhãn đã hoàn thiện được tải lên S3 với prefix `labels/`.
- Collector xác thực file nhãn và ghi các bản ghi hợp lệ vào DynamoDB.
- Chatbot truy xuất dữ liệu đã ghi thông qua hợp đồng News Retrieval hiện có.

### 1.1. Phạm vi thực hiện

1. Thu thập metadata từ các nguồn Fed/EIA chính thức đã được phê duyệt.
2. Chuẩn hóa URL, tiêu đề, tên nguồn và thời điểm xuất bản của bài viết.
3. Tạo mã định danh ổn định cho từng bài viết (`article_id`).
4. Lưu metadata đã thu thập vào S3 `pending/`.
5. Đọc file nhãn được chuẩn bị thủ công từ S3 `labels/`.
6. Xác thực cấu trúc file nhãn và mối liên hệ với bài viết đã thu thập.
7. Chuyển đổi nhãn hợp lệ theo hợp đồng dữ liệu DynamoDB `NewsLabels` hiện có.
8. Ghi dữ liệu bằng cơ chế ghi có điều kiện nhằm ngăn bản ghi trùng lặp và ghi đè.
9. Áp dụng IAM theo nguyên tắc quyền tối thiểu.
10. Bổ sung kiểm thử, logging và các biện pháp bảo vệ vận hành.

### 1.2. Ngoài phạm vi

- Tự động tóm tắt hoặc gán nhãn bằng Amazon Bedrock.
- Gọi Amazon Nova hoặc các foundation model khác.
- Tự động thực thi prompt hoặc retry quá trình gán nhãn bằng model.
- Thay thế trách nhiệm gán nhãn thủ công của Phước.
- Tạo thêm một bảng `NewsLabels` trùng lặp.
- Thay đổi hợp đồng API News Retrieval của chatbot nếu chưa có PR riêng được review.
- Triển khai hạ tầng AWS trong PR tài liệu này.

**Quyết định quy trình:** Cho đến khi bảo vệ dự án, Phước trực tiếp chuẩn bị summary và nhãn thủ công. Collector chỉ chịu trách nhiệm thu thập, xác thực và ghi dữ liệu, không phải dịch vụ gán nhãn bằng AI.

---

## 2. Nguồn tin và lịch phát hành

Chỉ sử dụng các nguồn tin chính thức từ Federal Reserve và EIA.

### 2.1. Federal Reserve — FOMC

Nguồn chính thức:

- Lịch họp FOMC: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- Tin tức và sự kiện Federal Reserve: https://www.federalreserve.gov/newsevents.htm

Collector cần nhận diện các tài liệu FOMC chính thức, bao gồm:

- Tuyên bố chính sách FOMC.
- Implementation notes khi có liên quan.
- Biên bản họp FOMC nếu nằm trong phạm vi thu thập được phê duyệt.
- Các thông báo chính thức liên quan đến cuộc họp và chính sách tiền tệ.

**Quy tắc xử lý thời điểm xuất bản:**

- Tuyên bố chính sách FOMC thông thường được công bố lúc 2:00 PM theo giờ miền Đông Hoa Kỳ (ET).
- Họp báo thường bắt đầu vào khoảng 2:30 PM ET.
- Các thông báo lịch sử hoặc ngoại lệ phải sử dụng thời điểm xuất bản thực tế từ nguồn chính thức.
- Không suy đoán timestamp lịch sử dựa trên lịch phát hành thông thường hiện tại.

Lịch FOMC chính thức là nguồn tham chiếu cho ngày họp và các tài liệu liên quan. Collector không được mặc định tất cả tài liệu trong cùng một cuộc họp đều có cùng thời điểm xuất bản.

**Yêu cầu backfill:** Phạm vi thời gian backfill lịch sử FOMC và loại tài liệu cần thu thập phải được xác nhận trước khi triển khai.

### 2.2. EIA — Weekly Petroleum Status Report

Nguồn chính thức:

- Weekly Petroleum Status Report: https://www.eia.gov/petroleum/supply/weekly/
- EIA Information Releases: https://ir.eia.gov/

WPSR thông thường được công bố vào thứ Tư lúc 10:30 AM ET. Trong các tuần có ngày nghỉ lễ, lịch phát hành có thể thay đổi.

Collector cần:

- Kiểm tra trang phát hành chính thức để xác định báo cáo và ngày phát hành thực tế.
- Ghi nhận timestamp xuất bản từ nguồn chính thức khi có thể.
- Không mặc định thứ Tư nào cũng có báo cáo được phát hành.
- Xử lý trường hợp báo cáo bị trì hoãn hoặc đổi lịch mà không tạo bài viết trùng lặp.

### 2.3. EIA — Today in Energy

Nguồn chính thức:

- Today in Energy: https://www.eia.gov/todayinenergy/
- Giới thiệu Today in Energy: https://www.eia.gov/todayinenergy/about.php

Today in Energy cung cấp các bài viết và phân tích về năng lượng nhiều lần trong tuần. Nguồn này không có một giờ phát hành cố định để collector hard-code.

Collector cần phát hiện bài viết mới từ trang chính thức hoặc RSS feed đã được xác nhận, nếu sử dụng. Thời điểm xuất bản phải lấy từ thông tin thực tế có trên nguồn.

### 2.4. Cấu hình nguồn và các thông tin cần xác nhận

| Hạng mục | Yêu cầu | Trạng thái |
|---|---|---|
| FOMC calendar URL | Sử dụng lịch chính thức của Federal Reserve | Đã xác định |
| FOMC article URLs | Trích xuất các tài liệu được liên kết chính thức | Đã xác định ở cấp nguồn |
| FOMC historical backfill | Xác nhận khoảng thời gian và loại tài liệu | TBD |
| WPSR URL | Sử dụng trang báo cáo tuần chính thức của EIA | Đã xác định |
| WPSR release time | Thông thường thứ Tư 10:30 AM ET; kiểm tra lịch thực tế | Có ngoại lệ ngày lễ |
| Today in Energy URL | Sử dụng trang chính thức của EIA | Đã xác định |
| Today in Energy publication time | Đọc timestamp thực tế, không hard-code | Đã xác định |
| RSS/feed endpoints | Xác nhận endpoint chính thức và điều khoản sử dụng | TBD |
| Quyền truy cập và lưu trữ | Kiểm tra điều khoản sử dụng và chính sách truy cập tự động | Cần xác minh |

Không tự tạo feed URL hoặc mặc định cấu trúc HTML của một trang web là API ổn định. Mọi RSS, API hoặc HTML parser được sử dụng phải được ghi rõ và kiểm thử với nguồn chính thức thực tế.

---

## 3. Quy trình thu thập và gán nhãn thủ công

### 3.1. Quy trình tổng thể

1. Collector kiểm tra các nguồn Fed/EIA chính thức đã được phê duyệt.
2. Phát hiện bài viết hoặc báo cáo mới.
3. Trích xuất và chuẩn hóa metadata bài viết.
4. Xác thực các trường metadata bắt buộc.
5. Tạo `article_id` ổn định.
6. Lưu metadata vào S3 `pending/`.
7. Phước xem xét dữ liệu đang chờ và thực hiện tóm tắt, gán nhãn thủ công.
8. Phước tải file nhãn hoàn chỉnh lên S3 `labels/`.
9. Collector đọc các file nhãn đã hoàn thiện từ `labels/`.
10. Collector xác thực cấu trúc nhãn và thông tin tham chiếu bài viết.
11. Collector chuyển đổi nhãn hợp lệ theo hợp đồng `NewsLabels` hiện có.
12. Collector ghi bản ghi bằng `PutItem` có điều kiện.
13. Collector ghi log kết quả xử lý và lỗi phát sinh.

### 3.2. Trách nhiệm của các S3 prefix

| Prefix | Mục đích | Người ghi | Người đọc |
|---|---|---|---|
| `pending/` | Metadata bài viết đã thu thập, đang chờ gán nhãn | Collector | Phước |
| `labels/` | Summary và nhãn thủ công đã hoàn thiện | Phước | Collector |

Hai prefix phải được tách biệt.

File metadata trong `pending/` không phải file nhãn hoàn chỉnh và tuyệt đối không được ghi trực tiếp vào `NewsLabels`.

### 3.3. Cấu trúc dữ liệu pending

Mỗi item trong `pending/` cần chứa đủ thông tin để Phước nhận diện và gán nhãn bài viết.

Các metadata dự kiến gồm:

- `article_id` ổn định.
- URL gốc của bài viết.
- URL đã chuẩn hóa, nếu khác URL gốc.
- Tiêu đề bài viết.
- Tên nguồn.
- Thời điểm xuất bản, nếu có.
- Thời điểm collector thu thập.
- Metadata đặc thù của nguồn cần thiết cho việc truy vết.

S3 object key và cấu trúc JSON chính xác phải được chốt trong PR triển khai.

Collector không được mặc định rằng đã có nhãn chỉ vì một item đã tồn tại trong `pending/`.

### 3.4. Trách nhiệm gán nhãn thủ công

Phước chịu trách nhiệm:

- Đọc và kiểm tra bài viết gốc từ nguồn chính thức.
- Chuẩn bị summary ngắn gọn.
- Xác định bài viết có liên quan đến các tài sản được hỗ trợ hay không.
- Gán impact score và direction theo quy tắc labeling đã thống nhất.
- Lưu file nhãn hoàn chỉnh vào `labels/`.

File nhãn phải chứa thông tin tham chiếu ổn định đến bài viết tương ứng trong `pending/`.

Quy tắc đối chiếu phải được xác định và xác thực trong quá trình triển khai, ưu tiên sử dụng `article_id` và URL gốc để truy vết.

Nếu file nhãn chưa tồn tại, sai định dạng hoặc không thể đối chiếu với bài viết trong `pending/`, collector không được tạo bản ghi `NewsLabels`.

### 3.5. Các giới hạn của collector

Collector không được:

- Gọi Amazon Bedrock.
- Gọi Nova hoặc foundation model khác.
- Tự tạo summary bài viết.
- Tự tạo nhãn tài sản.
- Retry quá trình labeling bằng model.
- Tự chỉnh sửa nhãn thủ công để làm cho dữ liệu có vẻ hợp lệ.

Quy trình này không yêu cầu quyền `bedrock:InvokeModel`.

---

## 4. Hợp đồng dữ liệu và ánh xạ DynamoDB

### 4.1. Bảng DynamoDB hiện có

Sử dụng bảng DynamoDB `NewsLabels` hiện có. Không tạo bảng trùng lặp.

Thiết kế khóa hiện tại:

- Partition key: `asset`
- Sort key: `sk`

Các giá trị asset được hỗ trợ:

- `gold`
- `silver`
- `brent`
- `wti`

Collector phải tuân thủ hợp đồng dữ liệu hiện tại trong `docs/api/contract.md`.

Nếu quá trình triển khai cần thay đổi contract, thay đổi đó phải được nêu rõ và review riêng, không được tự ý đưa vào một cấu trúc item khác.

### 4.2. Sort key

Sử dụng định dạng đã thống nhất:

`<published_at>#<article_id>`

Ví dụ:

`2026-10-13T10:45:00Z#3f9a1c0b7e2d4a61`

Phần timestamp phải được chuẩn hóa về UTC.

Timestamp trong `sk` phải trùng với giá trị `published_at` của bản ghi.

### 4.3. Định danh bài viết

Tạo `article_id` ổn định từ URL bài viết bằng SHA-256.

Có thể sử dụng 16 ký tự hexadecimal đầu tiên của SHA-256 để tạo mã định danh, phù hợp với quy ước trong `docs/api/contract.md`.

Trước khi tính hash, implementation phải sử dụng một biểu diễn URL nhất quán và xác định.

Các nguyên tắc:

- Cùng một URL đầu vào theo quy tắc chuẩn hóa đã thống nhất phải tạo ra cùng một `article_id`.
- Không tự ý loại bỏ query parameters nếu chưa xác định chúng không ảnh hưởng đến danh tính bài viết.
- Không sử dụng riêng tiêu đề bài viết làm khóa định danh.
- Lưu URL được sử dụng để tạo `article_id` để có thể truy vết và kiểm tra.

Quy tắc chuẩn hóa URL chi tiết phải được xác định và kiểm thử trong PR triển khai.

### 4.4. Các trường dữ liệu DynamoDB

Item cuối cùng phải tuân thủ hợp đồng `NewsLabels` hiện có.

Các trường nghiệp vụ bắt buộc theo contract:

| Trường | Ý nghĩa | Quy tắc xác thực |
|---|---|---|
| `asset` | Tài sản liên quan | `gold`, `silver`, `brent`, `wti` |
| `sk` | Thời điểm xuất bản và định danh bài viết | `<published_at>#<article_id>` |
| `title` | Tiêu đề bài viết | Không rỗng, tối đa 300 ký tự |
| `summary` | Nội dung tóm tắt thủ công | 1–3 câu, tối đa 600 ký tự |
| `link` | URL bài viết | URL HTTP hoặc HTTPS hợp lệ |
| `source` | Đơn vị phát hành | Chuỗi tên nguồn |
| `published_at` | Thời điểm xuất bản gốc | UTC, định dạng `YYYY-MM-DDTHH:MM:SSZ`, không có phần lẻ giây |
| `impact_score` | Mức độ tác động dự kiến | Số nguyên từ 0–3 |
| `direction` | Hướng tác động dự kiến | `bullish`, `bearish`, `mixed` hoặc `uncertain` |

`asset` và `sk` là hai khóa DynamoDB. Bảy trường còn lại là các trường nghiệp vụ của NewsLabels.

Các trường bổ sung như `article_id`, `confidence`, `event_type`, `fetched_at` hoặc `labeled_at` chỉ được thêm nếu phù hợp với contract và được chấp thuận trong PR triển khai.

**Bắt buộc xác minh contract:** Mapper phải tuân thủ `docs/api/contract.md`. Không được tự ý đổi tên, bỏ hoặc thay đổi kiểu dữ liệu của các trường hiện có.

### 4.5. Ánh xạ tài sản

Một bài viết có thể liên quan đến nhiều tài sản được hỗ trợ.

Collector cần tạo một item DynamoDB cho mỗi tài sản có liên quan, với:

- Cùng `article_id` cho cùng một bài viết.
- Partition key riêng theo từng tài sản.
- Sort key tương ứng.
- Giá trị nhãn đã được xác thực cho tài sản đó.

Quy tắc tạo item DynamoDB:

- `relevant=false`: không tạo item cho bất kỳ tài sản nào.
- `relevant=true`: chỉ tạo item cho tài sản có `impact_score > 0`.
- Tài sản có `impact_score=0` vẫn phải được giữ trong file nhãn thủ công để đáp ứng schema, nhưng không tạo item trong `NewsLabels`.
- Mỗi item được tạo phải sử dụng đúng `asset` và `sk` theo `docs/api/contract.md`.
- Không suy luận hoặc tự thay đổi nhãn của tài sản trong quá trình ánh xạ.

---

## 5. Schema nhãn và kiểm soát chất lượng

### 5.1. Nguồn schema

Sử dụng:

`docs/prompts/news-labeling-schema.json`

Schema này là tài liệu tham chiếu cấu trúc để xác thực file nhãn hoàn chỉnh, với điều kiện phải xác nhận rằng nó tương thích với định dạng đầu vào của quy trình gán nhãn thủ công.

Implementation phải phân biệt ba cấu trúc:

1. Cấu trúc JSON của file nhãn thủ công trong S3.
2. Cấu trúc item DynamoDB mà `NewsLabels` yêu cầu.
3. Contract phản hồi của chatbot trong `docs/api/contract.md`.

Các cấu trúc này có liên quan nhưng không mặc định giống nhau.

Collector phải ánh xạ tường minh từ file nhãn đã xác thực sang cấu trúc item DynamoDB.

### 5.2. Bộ benchmark labeling

`tests/labeling/real_cases_v3.json` từ commit `bdc6976` chứa bộ 50 trường hợp Fed/EIA thực tế đã được khóa để đánh giá chất lượng labeling.

Đây là bộ benchmark, không phải thư mục dữ liệu đầu vào production.

Quy tắc:

- Giữ benchmark tách biệt với `pending/` và `labels/`.
- Không tự động ghi benchmark vào `NewsLabels`.
- Không xem benchmark là nhãn production đang hoạt động.
- Giữ nguyên bộ benchmark đã khóa khi thực hiện đánh giá chất lượng.
- Sử dụng benchmark để đánh giá hướng dẫn gán nhãn thủ công hoặc một quy trình labeling riêng đã được phê duyệt.

### 5.3. Quy tắc xác thực

File nhãn phải được xác thực theo schema `docs/prompts/news-labeling-schema.json` trước khi xử lý.

**Xác thực cấu trúc file:**

- File phải có đủ các trường cấp gốc `relevant`, `asset_labels`, `event_type` và `notes`.
- Trường `relevant` phải có kiểu boolean.
- `asset_labels` phải có đủ bốn tài sản `gold`, `silver`, `brent`, `wti`.
- Mỗi tài sản phải có đủ `impact_score`, `direction`, `confidence` và `evidence`.
- `impact_score` phải là số nguyên thuộc phạm vi 0–3.
- `direction` phải thuộc một trong các giá trị `bullish`, `bearish`, `mixed`, `uncertain`.
- `confidence` phải thuộc một trong các giá trị `high`, `medium`, `low`.
- `evidence` phải tuân thủ kiểu dữ liệu và quy tắc trong schema.
- `event_type` phải thuộc danh sách giá trị được định nghĩa trong schema.
- `notes` phải tuân thủ kiểu dữ liệu và quy tắc trong schema.
- Không chấp nhận trường bổ sung nếu schema quy định `additionalProperties=false`.

**Quy tắc tạo item DynamoDB:**

- Nếu `relevant=false`, không tạo item cho bất kỳ tài sản nào.
- Nếu `relevant=true`, chỉ tạo item cho tài sản có `impact_score > 0`.
- Tài sản có `impact_score=0` vẫn được giữ trong file nhãn thủ công nhưng không tạo item trong `NewsLabels`.
- Không tự suy luận hoặc thay đổi `direction`, `impact_score`, `confidence` hay `evidence`.
- Không tự sửa hoặc bổ sung nhãn để làm cho file vượt qua validation.

**Quy tắc ánh xạ:**

- Metadata bài viết như `title`, `summary`, `link`, `source` và `published_at` phải được đối chiếu với bài viết tương ứng trong `pending/`.
- Chỉ tạo item DynamoDB sau khi cả file nhãn và metadata bài viết đều vượt qua validation.
- Quy tắc tạo item phải tuân theo mục 4.5 và contract `docs/api/contract.md`.

Không tự bổ sung quy tắc nghiệp vụ như `impact_score=0` bắt buộc phải có `direction=uncertain` nếu quy tắc đó chưa được quy định trong schema được phê duyệt.

### 5.4. Xử lý nhãn không hợp lệ hoặc chưa hoàn thiện

- File nhãn chưa tồn tại: giữ bài viết ở trạng thái chờ.
- File JSON sai định dạng: từ chối và ghi log.
- File không hợp lệ theo schema: từ chối và ghi log.
- Không đối chiếu được file với bài viết gốc: từ chối.
- Nhãn chứa asset không hỗ trợ hoặc score không hợp lệ: từ chối.
- Không ghi một phần dữ liệu rồi đánh dấu bài viết là đã hoàn tất.
- Cung cấp đủ thông tin lỗi để Phước có thể sửa file mà không ghi toàn bộ nội dung bài viết không cần thiết vào log.

### 5.5. Prompt injection và dữ liệu không đáng tin cậy

Nội dung bài viết, tiêu đề, summary, URL và nội dung file nhãn phải được xem là dữ liệu không đáng tin cậy.

Ngay cả khi labeling được thực hiện thủ công:

- Không thực thi các chỉ dẫn được nhúng trong bài viết.
- Không xem nội dung bài viết là chỉ dẫn dành cho collector.
- Không cho phép nội dung bài viết thay đổi cấu hình collector, IAM permissions hoặc quy trình xử lý.
- Xác thực mọi trường trước khi sử dụng trong log, object key hoặc DynamoDB.
- Tránh ghi toàn bộ nội dung không đáng tin cậy vào log.
- Không sử dụng nội dung bài viết để tạo câu lệnh thực thi hoặc policy động.

---

## 6. Idempotency và xử lý dữ liệu trùng lặp

Collector phải an toàn khi chạy lặp lại.

### 6.1. Định danh ổn định

Sử dụng cặp khóa `asset` và `sk` để xác định danh tính bản ghi DynamoDB.

Các lần thu thập lặp lại cùng một bài viết phải tạo ra cùng `article_id`.

Các lần ingest lặp lại cùng một file nhãn phải tạo ra cùng khóa DynamoDB.

### 6.2. Ghi có điều kiện

Sử dụng DynamoDB `PutItem` có điều kiện để ngăn ghi đè bản ghi đã tồn tại.

Điều kiện phải xác nhận khóa đích chưa tồn tại, sử dụng `attribute_not_exists` trên khóa phù hợp với thiết kế thực tế của bảng.

Hành vi mong đợi:

| Tình huống | Kết quả mong đợi |
|---|---|
| Bản ghi asset/article mới | Ghi mới |
| Xử lý lại cùng một bản ghi | Bỏ qua do trùng |
| Bản ghi đã tồn tại nhưng nội dung nhãn khác | Không ghi đè |
| File nhãn không hợp lệ | Từ chối |
| Một bài viết liên quan nhiều asset | Ghi một item cho mỗi asset liên quan |
| Một thao tác ghi asset thất bại | Ghi log lỗi và báo cáo chính xác trạng thái xử lý một phần |

Không sử dụng `PutItem` không có điều kiện trong quy trình ingest production.

**Lưu ý tương thích contract:**

Chính sách bỏ qua bản ghi trùng và không ghi đè trong kế hoạch này khác với hành vi replay được mô tả trong contract hiện tại.

Trước khi triển khai production, cần thống nhất và cập nhật contract thông qua PR riêng được review. PR triển khai Collector không được tự ý thay đổi contract hoặc âm thầm triển khai hai chính sách khác nhau.

Đối với bảng có partition key `asset` và sort key `sk`, implementation sử dụng conditional expression kiểm tra khóa partition chưa tồn tại, ví dụ `attribute_not_exists(asset)`, để ngăn ghi đè item có cùng khóa chính.

### 6.3. Chỉnh sửa và gán nhãn lại

Collector không được tự động ghi đè nhãn đã tồn tại.

Nếu Phước cần sửa nhãn sau khi dữ liệu đã được ingest, phải sử dụng một quy trình chỉnh sửa riêng đã được phê duyệt.

Quy trình chỉnh sửa phải bảo đảm khả năng truy vết và không làm suy yếu cơ chế idempotency của collector.

Cơ chế chỉnh sửa cụ thể là quyết định triển khai và phải được ghi rõ trước khi đưa vào production.

---

## 7. Tính toàn vẹn theo thời điểm, độ tin cậy và bảo mật

### 7.1. Point-in-time integrity

News features không được làm rò rỉ thông tin tương lai vào quá trình dự báo lịch sử.

- Sử dụng timestamp xuất bản gốc, không sử dụng timestamp thu thập, làm thời điểm của sự kiện tin tức.
- Chuẩn hóa timestamp về UTC.
- Một tin tức không được phép xuất hiện trong dữ liệu đầu vào của forecast nếu thời điểm cutoff của forecast sớm hơn thời điểm xuất bản tin đó.
- Không thay thế timestamp xuất bản bị thiếu bằng thời điểm thu thập.
- Các bài viết thiếu timestamp đáng tin cậy phải được đưa vào khu vực cách ly hoặc loại khỏi quá trình tạo feature theo thời gian.
- Lưu đủ metadata nguồn để có thể kiểm tra lại timestamp đã sử dụng.

Logic tạo feature ở các bước downstream phải áp dụng nhất quán cùng quy tắc cutoff.

### 7.2. Múi giờ và lịch chạy

Sử dụng múi giờ IANA:

`America/New_York`

Không hard-code một UTC offset cố định cho Eastern Time vì chênh lệch múi giờ thay đổi theo daylight saving time.

Lịch chạy phải tính đến:

- Ngày họp FOMC và thời điểm công bố thực tế.
- Lịch phát hành WPSR thông thường vào thứ Tư.
- Thay đổi lịch do ngày nghỉ của EIA và Federal Reserve.
- Các thông báo bị trì hoãn hoặc phát hành ngoài lịch.
- Lịch xuất bản thay đổi của Today in Energy.

EventBridge expression, tần suất chạy và cách xử lý daylight saving time phải được xác minh trong PR triển khai.

### 7.3. Độ tin cậy và retry

Retry không được tạo bản ghi DynamoDB trùng lặp.

- Retry các lỗi tạm thời từ nguồn tin, S3 hoặc DynamoDB với số lần giới hạn và backoff.
- Không retry lỗi xác thực dữ liệu vĩnh viễn như thể đó là lỗi tạm thời.
- Giữ lại định danh của các item thất bại để có thể xử lý lại.
- Không xóa file pending hoặc label chỉ vì một lần xử lý thất bại.
- Ghi nhận rõ trạng thái thành công một phần khi một bài viết tạo nhiều bản ghi asset nhưng chỉ một số thao tác ghi thành công.

Số lần retry, backoff, timeout và cơ chế dead-letter phải được chốt trong quá trình triển khai.

### 7.4. Secrets và quyền truy cập

- Không lưu AWS access key dài hạn trong source code.
- Sử dụng execution role của collector.
- Tuân thủ nguyên tắc least privilege.
- Không ghi credentials, token hoặc nội dung bài viết không cần thiết vào log.
- Giới hạn quyền S3 và DynamoDB theo đúng tài nguyên cần sử dụng.
- Không cấp quyền gọi model cho collector.

---

## 8. Hạ tầng, IAM, giám sát và chi phí

### 8.1. Quyền sở hữu hạ tầng

Hạ tầng của collector phải được triển khai thông qua CDK project hiện có và được review trong PR riêng, không gộp việc triển khai vào thay đổi tài liệu này.

PR triển khai phải xác định:

- CDK stack chịu trách nhiệm.
- Lambda hoặc tài nguyên thực thi khác.
- Execution role.
- Tham chiếu S3 bucket và prefix.
- Tham chiếu bảng `NewsLabels` hiện có.
- EventBridge schedule và timezone.
- Log group và thời gian lưu log.
- Cấu hình thông báo lỗi và alarm.

Không tạo bảng `NewsLabels` trùng lặp hoặc tạo các shared resources không cần thiết.

Ranh giới stack và người phụ trách phải được xác nhận với platform/CDK owner trước khi triển khai.

### 8.2. IAM permissions

Bảng dưới đây xác định ranh giới quyền truy cập dự kiến cho Collector và Phước. Implementation phải xác minh chính xác bucket ARN, object ARN và prefix conditions trong CDK trước khi triển khai.

| Principal | Action | Phạm vi tài nguyên | Mục đích |
|---|---|---|---|
| Collector | `s3:PutObject` | `pending/*` | Lưu metadata đã thu thập |
| Collector | `s3:GetObject` | `pending/*` | Đọc metadata để đối chiếu file nhãn với bài viết gốc |
| Collector | `s3:GetObject` | `labels/*` | Đọc nhãn thủ công đã hoàn thiện |
| Collector | `s3:ListBucket` | Bucket với prefix conditions cho `pending/` và `labels/` | Chỉ liệt kê các prefix cần thiết |
| Collector | `dynamodb:PutItem` | Bảng `NewsLabels` hiện có | Ghi bản ghi đã xác thực |
| Phước | `s3:GetObject` | `pending/*` | Đọc metadata đang chờ gán nhãn |
| Phước | `s3:ListBucket` | Bucket với prefix condition `pending/` | Liệt kê metadata đang chờ |
| Phước | `s3:PutObject` | `labels/*` | Tải file nhãn hoàn chỉnh |

**Ràng buộc quyền truy cập:**

- Collector chỉ được ghi object trong `pending/*`.
- Collector chỉ được đọc object trong `pending/*` và `labels/*`.
- Collector chỉ được liệt kê hai prefix `pending/` và `labels/`.
- Phước chỉ được đọc và liệt kê dữ liệu trong `pending/`.
- Phước chỉ được ghi object trong `labels/*`.
- Không cấp `bedrock:InvokeModel` cho Collector.
- Không cấp `dynamodb:Scan` hoặc quyền đọc DynamoDB rộng cho Collector.
- Không cấp quyền truy cập toàn bộ bucket cho Phước.
- Không cấp `s3:DeleteObject` nếu chưa có lý do và phê duyệt riêng.
- Không cấp quyền trên các prefix không liên quan.
- `s3:ListBucket` phải sử dụng bucket ARN và điều kiện `s3:prefix` phù hợp. Các object actions phải sử dụng object ARN.
- Không sử dụng quyền `s3:*` hoặc `dynamodb:*` thay cho các action cụ thể.
- Kiểm tra IAM policy bằng unit test, CDK assertions hoặc policy simulation trước khi deploy.

**Yêu cầu xác minh khi triển khai:**

1. Xác nhận tên S3 bucket và ARN thực tế.
2. Xác nhận execution role của Collector.
3. Xác nhận IAM principal mà Phước sẽ sử dụng.
4. Kiểm tra quyền đọc `pending/*` của Collector thực sự hoạt động.
5. Kiểm tra Collector không thể ghi vào `labels/*`.
6. Kiểm tra Phước không thể đọc `labels/*` hoặc ghi vào `pending/*`.
7. Kiểm tra quyền đọc hiện có của chatbot không bị thay đổi.

Quyền đọc hiện có của chatbot phải được giữ riêng biệt. Kế hoạch Collector này không cho phép mở rộng quyền chatbot một cách tùy tiện.

### 8.3. Giám sát và cảnh báo

Implementation cần cung cấp structured logs và các chỉ số vận hành cho:

- Số lượng bài viết phát hiện từ nguồn.
- Số lượng metadata mới được ghi vào pending.
- Số lượng bài viết trùng bị bỏ qua.
- Số lượng file nhãn được phát hiện.
- Số lượng file nhãn hợp lệ và không hợp lệ.
- Số lượng bản ghi DynamoDB được ghi thành công.
- Số lượng conditional write bị từ chối do trùng.
- Số lượng lỗi tạm thời và lỗi vĩnh viễn.
- Thời gian xử lý và lỗi thực thi.

Sử dụng quy ước alerting hiện có của dự án.

Tên SNS topic dự kiến cho môi trường development:

`cpaws-dev-alarms`

Phải xác nhận SNS topic ARN thực tế, trạng thái subscription, ngưỡng cảnh báo và thời gian lưu log với platform owner.

Không tự tạo hoặc hard-code topic ARN hay thời gian lưu log chưa được xác minh.

### 8.4. Chi phí

Quy trình đã thống nhất loại bỏ model inference khỏi collector.

Các thành phần chi phí dự kiến:

- Compute và thời gian thực thi collector.
- EventBridge scheduling.
- S3 storage và requests.
- DynamoDB writes.
- CloudWatch logs và metrics.
- SNS notifications nếu được cấu hình.

Collector không phát sinh chi phí inference Bedrock/Nova theo quy trình này vì việc gán nhãn được thực hiện thủ công bởi Phước.

Implementation cần tránh polling không cần thiết, ghi dữ liệu trùng, logging quá mức và backfill lịch sử không giới hạn.

---

## 9. Kế hoạch triển khai, kiểm thử và rollout

### 9.1. Trình tự triển khai

1. Xác nhận URL nguồn chính thức, feed endpoint, điều khoản truy cập và cách lấy timestamp.
2. Xác nhận phạm vi backfill FOMC và quy tắc thu thập WPSR/Today in Energy.
3. Xác nhận định dạng metadata pending và quy ước S3 object key.
4. Xác nhận định dạng file nhãn thủ công và mối liên hệ với `news-labeling-schema.json`.
5. Xác nhận ánh xạ DynamoDB theo `docs/api/contract.md`.
6. Xác nhận IAM policy và CDK stack ownership.
7. Triển khai chức năng thu thập và tạo pending objects.
8. Triển khai chức năng phát hiện và xác thực file nhãn thủ công.
9. Triển khai conditional DynamoDB writes.
10. Bổ sung logs, metrics, retry và alerts.
11. Chạy unit tests và integration tests.
12. Tạo PR triển khai riêng để review.
13. Chỉ deploy sau khi hoàn tất review và phê duyệt theo quy trình nhóm.

### 9.2. Các kiểm thử bắt buộc

**Kiểm thử nguồn và chuẩn hóa dữ liệu**

- Phân tích URL từ nguồn chính thức.
- Chuẩn hóa URL bài viết.
- Tạo `article_id` ổn định.
- Phân tích publication timestamp.
- Chuyển đổi UTC.
- Xử lý timestamp bị thiếu hoặc không hợp lệ.
- Phát hiện trùng lặp qua nhiều lần chạy.

**Kiểm thử S3 workflow**

- Tạo metadata object trong pending.
- Phân tách đúng các prefix.
- Đọc file nhãn hợp lệ.
- Xử lý khi chưa có file nhãn.
- Xử lý JSON sai định dạng.
- Xử lý `article_id` không tồn tại hoặc không khớp.
- Xử lý schema không hợp lệ.
- Không xóa nhầm file pending hoặc labels.

**Kiểm thử xác thực nhãn**

- Các giá trị asset được hỗ trợ.
- Impact score và direction hợp lệ.
- Giới hạn độ dài summary.
- Trường bắt buộc và kiểu dữ liệu.
- Xử lý bài viết không liên quan.
- Nhãn asset trùng lặp.
- Ánh xạ sang DynamoDB contract.

**Kiểm thử DynamoDB**

- Ghi bản ghi mới.
- Từ chối bản ghi trùng bằng conditional write.
- Không ghi đè nhãn đã tồn tại.
- Một bài viết có nhiều asset liên quan.
- Báo cáo lỗi ghi một phần.
- Partition key và sort key chính xác.

**Kiểm thử bảo mật và tính toàn vẹn**

- Collector không có quyền gọi Bedrock.
- Collector không thể ghi ngoài `pending/`.
- Collector chỉ đọc được `labels/`.
- Phước chỉ đọc được `pending/` và ghi được `labels/`.
- Không có quyền S3 hoặc DynamoDB quá rộng.
- Tin tức tương lai bị loại khỏi forecast có cutoff sớm hơn.
- Nội dung bài viết không đáng tin cậy không thể thay đổi quy trình xử lý.

**Kiểm thử vận hành**

- Retry khi gặp lỗi tạm thời.
- Không tạo vòng lặp retry với lỗi xác thực vĩnh viễn.
- Structured logging.
- Alarm được gửi thành công.
- Lịch chạy xử lý đúng daylight saving time và thay đổi lịch ngày lễ của Eastern Time.

### 9.3. Các mốc tiến độ

Các mốc thời gian được ghi nhận trong kế hoạch của nhóm:

| Mốc | Ngày mục tiêu | Kết quả cần đạt |
|---|---|---|
| Hoàn thành collector implementation | 03/11/2026 | Code và kiểm thử ban đầu |
| Có dữ liệu thực tế | 05/11/2026 | Dữ liệu Fed/EIA thực tế và nhãn đã xác thực |
| Bảo vệ/demo | 08/11/2026 | Quy trình có thể demo và JSON fallback |

Đây là các mốc mục tiêu, không phải bằng chứng rằng công việc đã hoàn thành. Người phụ trách phải cập nhật trạng thái thực tế trong project tracker.

### 9.4. Phương án dự phòng khi demo

Nếu việc thu thập nguồn chính thức hoặc gán nhãn thủ công không khả dụng trong buổi demo:

- Sử dụng JSON fixture được nhận diện rõ ràng.
- Đánh dấu các bản ghi fixture là dữ liệu mẫu/demo.
- Giữ fixture tách biệt khỏi `pending/` và `labels/` production.
- Không trình bày dữ liệu fixture như tin tức chính thức đang được thu thập trực tiếp.
- Nếu khả thi, demo vẫn phải đi qua cùng quy trình validation và DynamoDB mapping.

---

## 10. Tiêu chí nghiệm thu và các quyết định cần chốt

### 10.1. Tiêu chí nghiệm thu

Collector đủ điều kiện review khi:

1. Chỉ thu thập metadata từ các nguồn Fed/EIA chính thức đã được phê duyệt.
2. Lưu metadata đã thu thập vào `pending/`.
3. Phước có thể đọc pending và tải nhãn hoàn chỉnh vào `labels/` bằng đúng IAM permissions.
4. Collector chỉ đọc các file nhãn hoàn chỉnh từ `labels/`.
5. Nhãn không hợp lệ hoặc không khớp bài viết bị từ chối và ghi log.
6. Nhãn hợp lệ được ánh xạ đúng theo contract `NewsLabels` hiện có.
7. Conditional writes ngăn bản ghi trùng và ghi đè ngoài ý muốn.
8. Không có lời gọi Bedrock/Nova model.
9. Quy tắc point-in-time ngăn rò rỉ dữ liệu tương lai.
10. IAM tuân thủ least privilege.
11. Unit tests và integration tests bao phủ các luồng xử lý quan trọng.
12. Logs và alerts cung cấp đủ thông tin để vận hành và xử lý sự cố.
13. Implementation được review và phê duyệt thông qua PR riêng trước khi merge hoặc deploy.

### 10.2. Các quyết định phải xác nhận trước khi triển khai

| Quyết định | Nội dung cần xác nhận |
|---|---|
| Official feed/API endpoints | URL chính xác và phương thức truy cập được phép |
| Source terms | Quyền lưu trữ và truy cập tự động |
| FOMC backfill | Khoảng thời gian lịch sử và loại tài liệu cần thu thập |
| Timestamp extraction | Trường timestamp chính xác và cách xử lý fallback |
| Today in Energy schedule | Tần suất phát hiện bài mới; không giả định giờ phát hành cố định |
| Pending object format | JSON schema và quy ước object key |
| Manual label format | Trường bắt buộc và quy tắc đối chiếu `article_id` |
| Schema compatibility | `news-labeling-schema.json` có phải schema đầu vào chính thức cho nhãn thủ công hay không |
| DynamoDB mapping | Các trường và ràng buộc chính xác theo `docs/api/contract.md` |
| Idempotency | Conditional expression cuối cùng và quy trình sửa nhãn |
| CDK ownership | Stack, construct và người chịu trách nhiệm |
| EventBridge | Schedule expression và cách xử lý `America/New_York` |
| Reliability | Retry, timeout và xử lý item thất bại |
| Monitoring | ARN, thresholds và subscriptions của `cpaws-dev-alarms` |
| Logging | Thời gian lưu log và chính sách dữ liệu nhạy cảm |
| Backfill/demo fixtures | Người phụ trách và cách tách biệt với dữ liệu production |

Các giá trị chưa được xác nhận phải tiếp tục được đánh dấu `TBD` cho đến khi người phụ trách xác nhận. Không tự điền URL, ARN, lịch chạy, thời gian lưu log hoặc quyền IAM dựa trên suy đoán.

### 10.3. Quy tắc quản lý thay đổi

Tài liệu này xác định kế hoạch cho quy trình collector sử dụng manual labeling.

Mọi implementation làm thay đổi trách nhiệm đã thống nhất, data contract, ranh giới IAM hoặc quy trình labeling đều phải được đưa ra review.

Tất cả thay đổi Git phục vụ tích hợp hoặc triển khai phải tuân thủ quy trình PR và review của dự án. Tài liệu này không cấp quyền deploy hoặc merge trực tiếp.
