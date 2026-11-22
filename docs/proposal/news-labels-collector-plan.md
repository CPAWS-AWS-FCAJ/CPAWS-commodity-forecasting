# NewsLabels Collector – Implementation Plan

**Trạng thái:** Proposed – cập nhật theo các quyết định tại cuộc họp ngày 30/10/2026 và review PR #52
**Môi trường:** `cpaws-dev`
**Phạm vi:** Thu thập metadata tin tức/sự kiện chính thức, tạo hàng chờ để gán nhãn thủ công và ghi dữ liệu đã gán nhãn vào DynamoDB `NewsLabels`.
**Ngoài phạm vi:** Tự động tóm tắt, tự động phân loại bằng Bedrock, chatbot xử lý nội dung tin tức và thay đổi logic dự báo.

---

## 1. Mục tiêu và bối cảnh

NewsLabels Collector là thành phần hỗ trợ quy trình thu thập và gán nhãn tin tức/sự kiện phục vụ CPAWS.

Trong giai đoạn trước bảo vệ, quy trình gán nhãn được thực hiện thủ công bởi Phước. Collector chỉ chịu trách nhiệm phát hiện các bản tin chính thức thuộc phạm vi theo dõi, tạo metadata để Phước xử lý và đưa dữ liệu đã gán nhãn vào DynamoDB.

Quy trình được thiết kế theo nguyên tắc tách biệt:

1. Collector thu thập metadata và tạo hàng chờ trong S3.
2. Phước đọc metadata, kiểm tra nguồn tin và tự viết summary, nhãn.
3. Phước lưu kết quả gán nhãn vào S3.
4. Collector đọc kết quả đã gán nhãn và ghi vào DynamoDB `NewsLabels`.
5. Chatbot sử dụng dữ liệu trong `NewsLabels` theo contract hiện hành.

Trong giai đoạn này, Collector **không gọi Bedrock để tự gán nhãn**. Quyết định sử dụng nhãn thủ công đến giai đoạn bảo vệ được ghi nhận trong ADR-0013.

Tham chiếu:
- ADR-0013: Quyết định sử dụng quy trình gán nhãn thủ công đến giai đoạn bảo vệ.
- RFC #44: Quy tắc ghi dữ liệu có điều kiện vào `NewsLabels`.
- PR #52: Kế hoạch triển khai NewsLabels Collector.
- PR #77: Phương án đóng gói dữ liệu tin tức đã gán nhãn thủ công cho demo.

## 2. Phạm vi thu thập và nguồn dữ liệu

### 2.1. Nguồn tin chính thức

Collector theo dõi các nguồn chính thức sau:

| Nguồn | Nội dung theo dõi | URL |
|---|---|---|
| Federal Reserve – FOMC | FOMC statements và minutes | https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm |
| EIA – Weekly Petroleum Status Report (WPSR) | Báo cáo tồn kho và tình hình cung ứng dầu hàng tuần | https://www.eia.gov/petroleum/supply/weekly/ |
| EIA – Short-Term Energy Outlook (STEO) | Báo cáo triển vọng năng lượng ngắn hạn | https://www.eia.gov/outlooks/steo/ |
| EIA – Today in Energy | Bài viết liên quan trực tiếp đến thị trường dầu thô | https://www.eia.gov/todayinenergy/ |

Chỉ sử dụng nguồn chính thức của Federal Reserve và EIA. Không lấy nội dung từ trang tổng hợp tin tức hoặc nguồn không thuộc phạm vi đã thống nhất.

### 2.2. Phạm vi bài viết được thu thập

Collector chỉ đưa vào hàng chờ các nội dung thuộc một trong các nhóm sau:

- FOMC statements.
- FOMC minutes.
- Weekly Petroleum Status Report (WPSR).
- Short-Term Energy Outlook (STEO) và các bản cập nhật/dự báo chính thức liên quan.

Đối với mục Today in Energy, chỉ thu thập bài viết có tiêu đề đề cập trực tiếp đến ít nhất một trong các từ khóa hoặc chủ đề:

- Crude oil.
- Brent.
- WTI.
- STEO.

Không thu thập toàn bộ bài viết Today in Energy nếu không liên quan trực tiếp đến phạm vi trên.

### 2.3. Thời điểm công bố và múi giờ

Thời điểm công bố phải được xác định theo lịch hoặc metadata của nguồn chính thức:

| Nguồn | Quy tắc xác định thời điểm |
|---|---|
| FOMC | Sử dụng thời điểm công bố ghi trên lịch hoặc trang phát hành chính thức của Federal Reserve. |
| WPSR | Theo lịch phát hành chính thức của EIA; thời điểm công bố thông thường là 10:30 AM Eastern Time vào thứ Tư, có thể thay đổi do ngày nghỉ hoặc điều chỉnh lịch. |
| STEO | Theo lịch phát hành chính thức của EIA cho từng kỳ báo cáo. |
| Today in Energy | Sử dụng thời điểm xuất bản được công bố trong metadata hoặc trang bài viết; không tự gán giờ cố định nếu nguồn không cung cấp. |

Lưu timestamp theo UTC trong dữ liệu nội bộ. Khi đối chiếu lịch chạy Scheduler, sử dụng múi giờ `America/New_York`.

Không tự suy luận thời điểm xuất bản từ thời điểm Collector phát hiện bài viết.

### 2.4. Backfill

Backfill các bản tin FOMC từ ngày 28/10/2026 được thực hiện theo cùng quy trình và quy tắc chống ghi đè như dữ liệu thu thập mới.

Không tạo dữ liệu giả để thay thế bản tin chính thức. Nếu không tìm được metadata đáng tin cậy hoặc không xác định được thời điểm công bố, ghi nhận trường hợp đó để xử lý thủ công thay vì tự tạo giá trị.

## 3. Quy trình xử lý dữ liệu

Quy trình gán nhãn thủ công trong giai đoạn trước bảo vệ được thực hiện theo quyết định tại ADR-0013.

### 3.1. Luồng tổng thể

Quy trình gồm hai giai đoạn chính:

**Giai đoạn A – Tạo hàng chờ**

1. Collector truy cập các nguồn chính thức trong phạm vi.
2. Phát hiện bài viết hoặc báo cáo mới.
3. Chuẩn hóa metadata tối thiểu.
4. Tạo file `pending/<article_id>.json` trong S3.
5. Không đọc toàn bộ nội dung bài viết và không tự tạo summary hoặc nhãn.

**Giai đoạn B – Ghi nhãn đã hoàn tất**

1. Phước đọc metadata trong `pending/`.
2. Phước kiểm tra nguồn chính thức và tự viết summary, nhãn.
3. Phước tạo file `labels/<article_id>.json`.
4. Ở lần chạy tiếp theo, Collector phát hiện file nhãn tương ứng.
5. Collector đọc file trong `labels/`, kiểm tra schema và tính hợp lệ.
6. Collector ghi một item cho mỗi asset vào DynamoDB `NewsLabels` bằng conditional `PutItem`.
7. Nếu file nhãn chưa tồn tại hoặc không hợp lệ, Collector không ghi dữ liệu vào DynamoDB.

Không đưa dữ liệu chưa được gán nhãn vào `NewsLabels`.

### 3.2. Cơ chế theo dõi trạng thái trong S3

Sử dụng hai prefix cố định:

- `pending/`: metadata bài viết chờ Phước gán nhãn.
- `labels/`: dữ liệu đã được Phước gán nhãn.

Ví dụ:

```text
pending/
  <article_id>.json

labels/
  <article_id>.json
```

Collector sử dụng `s3:ListBucket` với điều kiện `s3:prefix` để liệt kê các object thuộc phạm vi được cấp quyền.

Quy tắc truy cập:

- Collector được `ListBucket` trong phạm vi prefix `pending/` và `labels/`.
- Collector được `PutObject` vào `pending/*`.
- Collector được `GetObject` từ `labels/*`.
- Collector **không được `GetObject` từ `pending/*`**.
- Collector không cần đọc nội dung file pending để xác định file nhãn đã tồn tại.
- Việc đối chiếu trạng thái hàng chờ được thực hiện dựa trên danh sách object key và `article_id`.

Collector không sử dụng DynamoDB `GetItem` để kiểm tra trạng thái xử lý. Không tạo thêm marker table hoặc yêu cầu quyền đọc DynamoDB ngoài phạm vi đã thống nhất.

File trong `labels/` là dấu hiệu cho biết Phước đã hoàn tất việc gán nhãn. Collector chỉ đọc nội dung file này khi xử lý dữ liệu đã gán nhãn.

### 3.3. Metadata trong pending

File `pending/<article_id>.json` chỉ chứa metadata cần thiết để Phước xác định và mở bài viết.

Ví dụ:

```json
{
  "article_id": "example-article-id",
  "title": "Official release title",
  "link": "https://www.example.gov/official-release",
  "published_at": "2026-11-05T14:30:00Z",
  "source": "EIA",
  "fetched_at": "2026-11-05T15:00:00Z"
}
```

Các trường bắt buộc:

- `article_id`: định danh ổn định của bài viết.
- `title`: tiêu đề gốc.
- `link`: URL nguồn chính thức.
- `published_at`: thời điểm xuất bản từ nguồn.
- `source`: tên nguồn phát hành.

`fetched_at` được sử dụng để ghi nhận thời điểm Collector phát hiện hoặc thu thập metadata.

Không lưu toàn bộ nội dung bài viết, không lưu summary do Collector tự tạo và không lưu nhãn dự đoán.

### 3.4. File labels

Phước tạo file `labels/<article_id>.json` theo schema đã thống nhất trong benchmark `tests/labeling/real_cases_v3.json`.

Ví dụ cấu trúc:

```json
{
  "title": "Official release title",
  "summary": "A concise factual Vietnamese summary of the official release.",
  "url": "https://www.example.gov/official-release",
  "published_at_utc": "2026-11-05T14:30:00Z",
  "source": "EIA",
  "release_type": "WPSR",
  "expected": {
    "relevant": true,
    "event_type": "oil_supply",
    "asset_labels": {
      "gold": {
        "impact_score": 0,
        "direction": "neutral",
        "confidence": 0.8,
        "evidence": "Evidence supporting the label."
      },
      "silver": {
        "impact_score": 0,
        "direction": "neutral",
        "confidence": 0.8,
        "evidence": "Evidence supporting the label."
      },
      "brent": {
        "impact_score": 2,
        "direction": "bearish",
        "confidence": 0.9,
        "evidence": "Evidence supporting the label."
      },
      "wti": {
        "impact_score": 2,
        "direction": "bearish",
        "confidence": 0.9,
        "evidence": "Evidence supporting the label."
      }
    }
  }
}
```

Đây là ví dụ minh họa cấu trúc, không phải nhãn mặc định cho dữ liệu thực tế.

Quy tắc gán nhãn:

- `title`: giữ nguyên tiêu đề tiếng Anh của nguồn chính thức.
- `summary`: viết bằng tiếng Việt, tối đa 1–2 câu và không quá 300 ký tự.
- `summary` chỉ nêu thông tin thực tế có trong nguồn, không đưa ý kiến hoặc suy đoán.
- `url`: trỏ đến nguồn chính thức.
- `published_at_utc`: thời điểm công bố quy đổi về UTC.
- `source`: nguồn phát hành.
- `release_type`: loại bản tin hoặc báo cáo.
- `expected.relevant`: xác định bản tin có liên quan đến phạm vi CPAWS hay không.
- `expected.event_type`: phân loại loại sự kiện.
- `expected.asset_labels`: phải có nhãn cho đủ bốn asset `gold`, `silver`, `brent`, `wti`.
- Mỗi asset label phải có `impact_score`, `direction`, `confidence`, `evidence`.

`tests/labeling/real_cases_v3.json` là benchmark để đối chiếu schema và chất lượng nhãn, không phải nguồn dữ liệu production.

### 3.5. Kiểm tra trước khi ghi DynamoDB

Collector phải kiểm tra:

1. File labels có tồn tại và đọc được hay không.
2. JSON có hợp lệ hay không.
3. Các trường bắt buộc có đầy đủ hay không.
4. URL có thuộc nguồn chính thức tương ứng hay không.
5. `published_at_utc` có định dạng timestamp UTC hợp lệ hay không.
6. `asset_labels` có đủ bốn asset hay không.
7. Các giá trị nhãn có đúng kiểu dữ liệu và phạm vi được schema cho phép hay không.

Nếu dữ liệu không hợp lệ:

- Không ghi item tương ứng vào DynamoDB.
- Ghi log lỗi đủ để truy vết.
- Không tự sửa hoặc tự suy luận nhãn.
- Giữ nguyên file labels để Phước kiểm tra và sửa thủ công.

## 4. Kiến trúc triển khai AWS

### 4.1. Thành phần

| Thành phần | Vai trò |
|---|---|
| EventBridge Scheduler | Kích hoạt Collector theo lịch. |
| Lambda NewsLabels Collector | Thu thập metadata, kiểm tra file labels và ghi dữ liệu đã gán nhãn. |
| S3 `cpaws-dev-lake` | Lưu metadata pending và dữ liệu labels. |
| DynamoDB `NewsLabels` | Lưu dữ liệu tin tức/sự kiện đã gán nhãn. |
| CloudWatch Logs | Lưu log hoạt động của Lambda. |
| CloudWatch Alarm | Phát hiện lỗi Lambda. |
| SNS `cpaws-dev-alarms` | Nhận thông báo từ alarm. |

### 4.2. CDK stack

Tạo stack riêng:

`CpawsNews`

Stack này tham chiếu đến các tài nguyên đã tồn tại:

- S3 lake bucket `cpaws-dev-lake`.
- DynamoDB table `NewsLabels`.
- SNS topic `cpaws-dev-alarms`.

Không thêm Collector vào `CpawsData`.

Không tạo lại bucket hoặc DynamoDB table nếu tài nguyên tương ứng đã được quản lý ở stack khác.

Stack chỉ chịu trách nhiệm tạo và cấu hình tài nguyên thuộc phạm vi NewsLabels Collector.

### 4.3. Lambda

Lambda Collector chịu trách nhiệm:

- Lấy dữ liệu từ các nguồn chính thức.
- Chuẩn hóa metadata.
- Tạo file pending.
- Liệt kê trạng thái các object theo prefix.
- Đọc file labels đã hoàn tất.
- Kiểm tra schema.
- Ghi item vào DynamoDB bằng conditional `PutItem`.
- Ghi log và báo lỗi khi xử lý thất bại.

Không tích hợp Bedrock trong Lambda Collector.

Không đưa logic chatbot hoặc logic dự báo vào Lambda này.

### 4.4. EventBridge Scheduler

Lịch chạy dự kiến:

```text
cron(30 15 ? * MON-FRI *)
```

Cấu hình:

```text
ScheduleExpressionTimezone=America/New_York
```

Lịch chạy tương ứng 15:30 theo giờ New York, từ thứ Hai đến thứ Sáu.

Việc sử dụng timezone được cấu hình trực tiếp trong Scheduler, không tự cộng hoặc trừ giờ trong code Lambda.

Scheduler chỉ kích hoạt Collector. Không dùng lịch chạy để giả định rằng mọi nguồn đều đã phát hành dữ liệu.

### 4.5. Retry và xử lý lỗi

Cấu hình retry của Scheduler target:

```text
MaximumRetryAttempts = 0
```

Không tự động retry ở tầng Scheduler.

Lỗi trong quá trình xử lý phải được ghi log rõ ràng để có thể xác định nguồn, bài viết và bước xử lý bị lỗi.

Conditional `PutItem` là cơ chế bảo vệ dữ liệu khi gặp bản ghi trùng, không phải lý do để retry vô hạn.

### 4.6. CloudWatch Logs và Alarm

Log retention:

```text
1 month
```

Thời gian lưu log thống nhất với Lambda predict hiện có.

Tạo CloudWatch Alarm theo dõi metric `Errors` của Lambda Collector.

Alarm gửi thông báo đến SNS topic hiện có:

```text
cpaws-dev-alarms
```

Không tạo SNS topic mới nếu topic hiện tại đáp ứng được yêu cầu.

## 5. Quyền IAM

### 5.1. Nguyên tắc

Áp dụng least privilege. Collector chỉ có quyền cần thiết cho đúng prefix và đúng DynamoDB table.

Không cấp quyền rộng trên toàn bộ bucket hoặc toàn bộ DynamoDB.

Không sử dụng long-term access keys.

### 5.2. IAM của Collector

| Service | Action | Resource / Condition | Mục đích |
|---|---|---|---|
| S3 | `s3:ListBucket` | Bucket `cpaws-dev-lake`, giới hạn `s3:prefix` | Liệt kê object trong phạm vi pending và labels. |
| S3 | `s3:PutObject` | `pending/*` | Tạo metadata hàng chờ. |
| S3 | `s3:GetObject` | `labels/*` | Đọc dữ liệu đã được gán nhãn. |
| DynamoDB | `dynamodb:PutItem` | Table `NewsLabels` | Ghi dữ liệu đã gán nhãn. |

Không cấp cho Collector:

- `s3:GetObject` trên `pending/*`.
- `s3:DeleteObject`.
- `dynamodb:GetItem`.
- `dynamodb:Scan`.
- `dynamodb:DeleteItem`.
- `dynamodb:UpdateItem`.
- `bedrock:InvokeModel`.

Đối với `s3:ListBucket`, policy phải giới hạn prefix bằng điều kiện `s3:prefix`, không cấp quyền liệt kê toàn bucket không giới hạn.

### 5.3. IAM của Phước

Quyền của Phước được cấp riêng, không gộp vào execution role của Collector.

| Service | Action | Resource / Condition | Mục đích |
|---|---|---|---|
| S3 | `s3:ListBucket` | Bucket `cpaws-dev-lake`, prefix `pending/` | Liệt kê metadata đang chờ. |
| S3 | `s3:GetObject` | `pending/*` | Đọc metadata để mở nguồn chính thức. |
| S3 | `s3:PutObject` | `labels/*` | Lưu dữ liệu đã gán nhãn. |

Không cấp quyền xóa pending hoặc labels nếu không có yêu cầu riêng được phê duyệt.

### 5.4. IAM review

Policy phải được review theo đúng phạm vi tài nguyên và prefix.

- Collector role không được đọc `pending/*`.
- Phước có quyền đọc `pending/*` và ghi `labels/*`.
- Collector chỉ đọc `labels/*`.
- Không có quyền Bedrock trong Collector role.
- Không có quyền Scan hoặc GetItem trên DynamoDB.

Các thay đổi IAM phải được review trước khi tích hợp.

## 6. Quy tắc ghi DynamoDB NewsLabels

### 6.1. Nguyên tắc ghi

Chỉ ghi dữ liệu đã được Phước gán nhãn và vượt qua kiểm tra schema.

Mỗi file labels có thể tạo tối đa bốn item tương ứng với:

- `gold`
- `silver`
- `brent`
- `wti`

Mỗi item phải giữ được thông tin nguồn để truy vết bài viết gốc và nhãn đã gán.

Không ghi dữ liệu pending vào DynamoDB.

### 6.2. Conditional PutItem

Thực hiện ghi bằng `PutItem` có điều kiện theo RFC #44.

Condition expression phải sử dụng chính xác:

```text
attribute_not_exists(asset) AND attribute_not_exists(sk)
```

Mục tiêu:

- Không ghi đè item đã tồn tại.
- Không làm thay đổi dữ liệu đã được ghi trước đó.
- Khi item trùng khóa, xử lý như bản ghi đã tồn tại và ghi nhận kết quả phù hợp trong log.
- Không xóa hoặc cập nhật item cũ để thay thế bằng dữ liệu mới.

Không sử dụng `PutItem` không có điều kiện.

Không thêm cơ chế `GetItem` trước khi ghi để kiểm tra trùng. Conditional `PutItem` là cơ chế bảo vệ dữ liệu tại thời điểm ghi.

### 6.3. Xử lý bản ghi trùng

Nếu DynamoDB trả về lỗi conditional check do item đã tồn tại:

- Không ghi đè.
- Không xóa item hiện tại.
- Không retry cùng một item theo cách bỏ qua điều kiện.
- Ghi nhận trạng thái duplicate/already exists trong log.
- Tiếp tục xử lý các asset khác nếu không có lỗi nghiêm trọng ảnh hưởng toàn bộ lần chạy.

Nếu lỗi không phải conditional check, ghi log và xử lý theo cơ chế lỗi đã định nghĩa.

### 6.4. Truy vết

Dữ liệu được ghi vào `NewsLabels` phải giữ các trường cần thiết để xác định:

- Bài viết nguồn.
- URL chính thức.
- Thời điểm xuất bản.
- Nguồn phát hành.
- Loại sự kiện.
- Asset tương ứng.
- Nhãn và bằng chứng gán nhãn.

Không tự tạo thêm schema hoặc thay đổi contract DynamoDB ngoài phạm vi RFC #44 và contract API đã thống nhất.

## 7. Bảo mật và chất lượng dữ liệu

### 7.1. Nguồn dữ liệu

Chỉ chấp nhận nguồn chính thức trong danh sách tại mục 2.

URL phải được kiểm tra theo domain nguồn tương ứng. Không coi nội dung từ URL không xác định là dữ liệu chính thức.

### 7.2. Prompt injection

Dù giai đoạn này không sử dụng Bedrock, nội dung tin tức vẫn được xem là dữ liệu không đáng tin cậy.

Không xem nội dung bài viết, tiêu đề hoặc metadata từ nguồn bên ngoài là chỉ thị thực thi.

Không thực thi mã, lệnh hoặc nội dung nhúng trong dữ liệu thu thập.

Không đưa nội dung bài viết vào prompt hoặc quy trình tự động thực thi trong phạm vi Collector.

### 7.3. Chất lượng nhãn

Phước chịu trách nhiệm kiểm tra nội dung nguồn và gán nhãn thủ công.

Summary phải:

- Giữ đúng ý nghĩa của nguồn chính thức.
- Viết bằng tiếng Việt.
- Không quá 300 ký tự.
- Không đưa nhận định đầu tư hoặc dự báo chủ quan.
- Không thêm dữ kiện không có trong nguồn.

Nhãn cho từng asset phải có bằng chứng hỗ trợ. Không suy diễn rằng một sự kiện ảnh hưởng giống nhau đến cả bốn asset.

### 7.4. Chatbot

Chatbot tiếp tục sử dụng contract hiện hành để đọc dữ liệu NewsLabels.

Bộ lọc `min_impact >= 2` trong `get_news` được giữ nguyên theo quyết định hiện tại.

Collector không thay đổi logic truy vấn, cách lọc tin hoặc cách chatbot giải thích kết quả.

## 8. Kiểm thử và tiêu chí nghiệm thu

### 8.1. Unit tests

Kiểm thử các nhóm chức năng:

- Chuẩn hóa metadata từ nguồn chính thức.
- Tạo file pending đúng schema.
- Xác định bài viết thuộc phạm vi theo dõi.
- Bỏ qua bài viết ngoài phạm vi.
- Liệt kê object theo prefix.
- Phát hiện file labels tương ứng.
- Đọc và parse file labels.
- Kiểm tra trường bắt buộc.
- Kiểm tra đủ bốn asset.
- Từ chối dữ liệu sai schema.
- Ghi DynamoDB bằng conditional `PutItem`.
- Xử lý conditional check failure.
- Xử lý lỗi S3 và DynamoDB.
- Không gọi Bedrock.

### 8.2. IAM tests / review

Xác nhận Collector role:

- Có `PutObject` trên `pending/*`.
- Có `GetObject` trên `labels/*`.
- Có `ListBucket` giới hạn bằng `s3:prefix`.
- Có `PutItem` trên đúng bảng `NewsLabels`.
- Không có `GetObject` trên `pending/*`.
- Không có `DeleteObject`.
- Không có DynamoDB `GetItem`, `Scan`, `UpdateItem`, `DeleteItem`.
- Không có `bedrock:InvokeModel`.

Xác nhận quyền Phước được tách riêng khỏi Collector role.

### 8.3. Integration tests

Kiểm thử luồng:

1. Collector phát hiện một bản tin chính thức mới.
2. Collector tạo `pending/<article_id>.json`.
3. Phước tạo `labels/<article_id>.json`.
4. Collector phát hiện file labels.
5. Collector đọc và kiểm tra schema.
6. Collector ghi item cho các asset vào `NewsLabels`.
7. Chạy lại Collector với cùng dữ liệu.
8. Xác nhận item đã tồn tại không bị ghi đè.

Kiểm thử thêm các trường hợp:

- Không có file labels.
- File labels JSON không hợp lệ.
- Thiếu asset label.
- Timestamp sai định dạng.
- URL không thuộc nguồn chính thức.
- DynamoDB trả về conditional check failure.
- S3 hoặc DynamoDB phát sinh lỗi.

### 8.4. Tiêu chí nghiệm thu

Chỉ xem Collector đạt yêu cầu khi:

- Thu thập đúng các nguồn và phạm vi đã thống nhất.
- Chỉ tạo pending metadata, không tự gán nhãn.
- Đọc được labels do Phước tạo.
- Ghi đúng schema DynamoDB.
- Conditional `PutItem` hoạt động và không ghi đè.
- IAM đúng least privilege.
- Scheduler sử dụng đúng timezone.
- Alarm gửi đến SNS hiện có.
- Log retention là một tháng.
- Unit tests và integration tests đạt.
- PR đã được review và merge theo quy trình dự án.

## 9. Timeline và phương án demo

### 9.1. Demo ngày 08/11/2026

Demo ngày 08/11 sử dụng bộ JSON tin tức đã được gán nhãn thủ công và đóng gói trong Lambda Chat API theo phương án PR #77.

Đường dẫn package:

```text
infra/lambda/chat_api/news/
```

Bộ dữ liệu demo được Phước gán nhãn thủ công từ các bản tin chính thức có thật.

Đây không phải dữ liệu giả, không phải fixture mô phỏng tác động và không phụ thuộc vào Collector.

Trong cấu hình demo này:

```text
NEWS_TABLE_NAME=
```

Collector không phải dependency của demo ngày 08/11. Việc Collector chưa hoàn tất không làm ảnh hưởng đến luồng chatbot đã chuẩn bị cho bảo vệ.

### 9.2. Timeline triển khai Collector

| Thời gian | Công việc | Người phụ trách |
|---|---|---|
| 09–15/11/2026 | Triển khai Collector code và CDK trong PR riêng | Tuấn |
| Trong quá trình triển khai | Review CDK | `@CTMT1406` |
| Trong quá trình triển khai | Review IAM | Tuấn |
| Trước 22/11/2026 | Hoàn thành lần chạy thực tế và có dữ liệu trong NewsLabels trước thời điểm freeze | Tuấn phối hợp Phước |
| Sau khi có dữ liệu | Kiểm tra tích hợp với contract và chatbot | Nhóm phụ trách API/chatbot |

Mọi thay đổi code hoặc CDK phải đi qua PR, được review và merge trước khi xem là hoàn tất tích hợp.

### 9.3. Phương án nếu Collector chậm tiến độ

Nếu Collector chưa hoàn tất trước thời điểm demo:

- Tiếp tục sử dụng bộ JSON tin tức chính thức đã được Phước gán nhãn thủ công.
- Đóng gói dữ liệu trong Lambda Chat API theo PR #77.
- Không chờ Collector để thực hiện demo.
- Không đưa dữ liệu giả hoặc nhãn tự sinh vào demo.
- Không thay đổi logic chatbot chỉ để phụ thuộc vào Collector.

Nếu Collector hoàn thành sau demo, nhóm tiếp tục triển khai và kiểm thử theo timeline mục 9.2.

### 9.4. Phương án dữ liệu dự phòng

Dữ liệu dự phòng phải là các bản tin hoặc báo cáo chính thức có thật từ Federal Reserve hoặc EIA, được Phước kiểm tra và gán nhãn thủ công.

Bộ dữ liệu này được đóng gói theo cấu trúc mà Chat API đang sử dụng.

Không sử dụng dữ liệu sample tự tạo để giả lập bản tin thật.

Không thay thế nguồn chính thức bằng bài viết tổng hợp hoặc nội dung không thể xác minh.

Phương án dự phòng chỉ phục vụ demo; không thay thế mục tiêu triển khai Collector và ghi dữ liệu thực tế vào NewsLabels trước thời điểm freeze 22/11.

## 10. Quyết định, trách nhiệm và các giá trị cần chốt

### 10.1. Các quyết định đã thống nhất

| Nội dung | Quyết định |
|---|---|
| Quy trình gán nhãn trước bảo vệ | Phước gán nhãn thủ công. |
| Bedrock trong Collector | Không sử dụng. |
| Prefix metadata chờ xử lý | `pending/`. |
| Prefix dữ liệu đã gán nhãn | `labels/`. |
| Cơ chế nhận biết đã gán nhãn | Đối chiếu object key trong S3; file labels là dấu hiệu hoàn tất. |
| Collector đọc pending | Không có `GetObject` trên `pending/*`. |
| Collector đọc labels | Có `GetObject` trên `labels/*`. |
| Collector ghi DynamoDB | Conditional `PutItem` theo RFC #44. |
| Condition expression | `attribute_not_exists(asset) AND attribute_not_exists(sk)`. |
| Marker table riêng | Không sử dụng. |
| Bedrock IAM | Không cấp `bedrock:InvokeModel`. |
| CDK stack | Tạo stack riêng `CpawsNews`, không thêm vào `CpawsData`. |
| Scheduler | `cron(30 15 ? * MON-FRI *)`, timezone `America/New_York`. |
| Scheduler retry | `MaximumRetryAttempts = 0`. |
| Alarm | Lambda Errors gửi đến SNS `cpaws-dev-alarms`. |
| Log retention | Một tháng. |
| Demo 08/11 | Dùng JSON tin tức chính thức đã gán nhãn thủ công, đóng gói trong Lambda Chat API theo PR #77. |
| Thời hạn dữ liệu thực tế | Có dữ liệu trong NewsLabels trước freeze 22/11/2026. |

### 10.2. Các giá trị cần xác nhận

Các giá trị chưa có quyết định cuối cùng phải được giữ ở trạng thái `TBD`. Không tự đặt giá trị mặc định trong code hoặc CDK trước khi có xác nhận.

| Nội dung | Trạng thái | Người phụ trách | Hạn xác nhận |
|---|---|---|---|
| Tên construct và tên resource cụ thể trong stack `CpawsNews` | TBD | Tuấn | Trước khi hoàn tất CDK PR, 15/11/2026 |
| Timeout và memory chính thức của Lambda Collector | TBD | Tuấn | Trước khi hoàn tất CDK PR, 15/11/2026 |
| Giới hạn số lượng bài viết tối đa mỗi lần chạy | TBD | Tuấn | Trước khi hoàn tất Collector code, 15/11/2026 |
| Cách xử lý cụ thể khi nguồn chính thức thay đổi cấu trúc hoặc không truy cập được | TBD | Tuấn | Trước lần chạy thực tế đầu tiên |
| Xác nhận cuối cùng về schema item `NewsLabels` theo contract/RFC đang được tích hợp | TBD | Tuấn phối hợp người phụ trách NewsLabels contract | Trước integration test |
| Xác nhận quyền truy cập S3 của Phước trên môi trường `cpaws-dev` | TBD | Người phụ trách IAM và Phước | Trước lần gán nhãn thực tế đầu tiên |

Các giá trị trong bảng chỉ được chuyển khỏi `TBD` sau khi có xác nhận của người phụ trách tương ứng.

### 10.3. Trách nhiệm

| Người phụ trách | Trách nhiệm |
|---|---|
| Tuấn | Triển khai Collector code và CDK; review IAM; phối hợp kiểm thử tích hợp. |
| `@CTMT1406` | Review CDK. |
| Phước | Kiểm tra nguồn chính thức, viết summary và gán nhãn thủ công, lưu file vào `labels/`. |
| Người phụ trách API/Chatbot | Duy trì contract và kiểm tra khả năng sử dụng dữ liệu NewsLabels. |
| Khải và Tiến | Review lại kế hoạch sau khi cập nhật theo các quyết định đã thống nhất. |

### 10.4. Quy trình review

Sau khi cập nhật tài liệu:

1. Gửi lại PR #52 để Khải review.
2. Gửi lại PR #52 để Tiến review.
3. Tiếp nhận và xử lý các nhận xét còn lại.
4. Chỉ xem tài liệu được thông qua khi các review cần thiết đã được xác nhận.
5. Các thay đổi code, IAM và CDK tiếp theo phải được thực hiện qua PR riêng và tuân thủ quy trình review/merge của dự án.
