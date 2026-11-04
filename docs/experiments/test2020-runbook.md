# Runbook cho lần đánh giá test2020 duy nhất

Tài liệu hướng dẫn vận hành tương lai theo [kế hoạch #75](test2020-plan.md) và review runner #85. Các bước bên dưới chưa được thực hiện bởi việc soạn runbook. Chỉ Long chạy sau khi nhóm cho phép; Khải review kết quả. Không có DT, SHA-256 hoặc xác nhận deployment được suy đoán trong tài liệu này.

## 1. Chốt snapshot theo thời điểm merge kế hoạch

Theo mốc merge #75 do nhóm cung cấp, **2026-11-03T09:59Z**, xác định snapshot clean mới nhất đã tồn tại tại thời điểm đó. Đối chiếu lịch sử object/version và bằng chứng vận hành để xác minh DT thực tế; không dùng ngày tải xuống hoặc bản hiện hành đã bị overwrite làm bằng chứng lịch sử. Nếu không xác minh được snapshot đúng mốc, dừng và yêu cầu nhóm quyết định.

Người được phân quyền lấy đúng bytes của ba file `prices.parquet`, `rejected.parquet`, `quality.json` trong snapshot đã chọn và tính SHA-256 riêng cho từng file. Ở bước này chỉ đọc bytes để băm, **không giải mã Parquet, xem giá, tính metric hoặc chạy evaluation**. Giữ identity/version của object và lineage nguồn yfinance, target symbols, commit tạo dữ liệu cùng audit reference. Không chọn lại snapshot dựa trên kết quả test.

## 2. Chốt tài liệu bằng PR riêng

Nhóm cập nhật DT và ba SHA-256 đã xác minh tại §8 của kế hoạch #75; ghi vào §9 quyết định giữ DM calendar-gap policy hiện tại, không triển khai chính sách gap mới trong lần chạy này. Đưa thay đổi tài liệu qua review và merge bằng **PR riêng** trước khi tính execution hash. Không sửa §8–§9 trong gói sửa runner #85 này.

## 3. Freeze runner và commit

Runner, tests và protocol cuối cùng phải được review/merge vào `developer`. Chọn full commit SHA sạch chứa các thay đổi đã chốt. Không sửa tracked files hoặc để untracked files trong checkout thực thi; output và execution metadata đặt ngoài repository.

Official preflight thực hiện các lệnh tương đương sau (chỉ vận hành khi được nhóm cho phép):

```text
git fetch origin +refs/heads/developer:refs/remotes/origin/developer
git rev-parse refs/remotes/origin/developer
git merge-base --is-ancestor <runner_commit> <resolved_origin_developer_sha>
```

Runner khóa full SHA đã resolve cho cả kiểm tra ancestry và trường `origin_developer_sha` trong claim. Không dùng local `developer` làm bằng chứng merge. Fetch/ref/status lỗi, SHA không hợp lệ, commit không phải ancestor hoặc lỗi ancestry đều phải dừng trước claim và trước đọc snapshot; không fallback về local branch. Kiểm tra này chứng minh quan hệ history, không tự chứng minh reviewer đã approve; approval vẫn là điều kiện vận hành của nhóm.

## 4. Tính protocol/config hash từ commit đã freeze

Chỉ thực hiện sau khi §8–§9 đã cập nhật và merge. Tại đúng checkout sạch đã khóa, dùng `src.eval.run_test2020.protocol_hash(<full_runner_commit>)`. Hàm lấy danh sách committed files bằng Git tree và bytes bằng `git show <commit>:<relative_path>`; phạm vi vẫn là mọi Python file dưới `src/`, `configs/` và `docs/experiments/test2020-plan.md`.

Hash tổng giữ cấu trúc protocol configuration và map path → SHA-256 source như runner; thay đổi ở đây là nguồn bytes từ Git blob thay vì newline của working tree. Metadata hiện hành dùng trường **`config_hash`** cho giá trị hash tổng này, không thêm một giá trị protocol hash khác với cách tính riêng. Reviewer có thể tái tính từ cùng commit. Không sửa các file tham gia hash sau freeze, không fallback về working tree nếu thiếu blob. Các hash khóa theo cách cũ cần được tính lại theo implementation đã review, trước claim; không sửa hash sau khi xem kết quả.

## 5. Xác nhận môi trường và execution metadata

Dùng Python 3.11 cùng dependencies của repository và chạy unit tests synthetic/CI đã yêu cầu trước khi được phép đánh giá. Không dùng test data thật để debug code. Xác nhận seed 7, B=2000, block chính 20, sensitivity CI block 10/40, cutoff và hai model đúng [locked config](../../configs/test2020.py). Runner kiểm λ S1a giữa config và K3b; clip phải đồng nhất giữa config, K3b và core. Bất đồng phải dừng, không sửa ngầm bằng default.

Chuẩn bị execution metadata theo `REQUIRED_METADATA`: run_id cố định, full runner commit, snapshot DT, map ba SHA-256, lineage, config_hash, operator Long, plan_reference và approval cho official run. Lineage cần source, symbols, data_commit và reference thực đã được duyệt. Không đặt cờ approval khi chưa có phê duyệt; không dùng placeholder làm metadata chạy thật. Kiểm tra đường dẫn snapshot có tên `dt=<DT>` và output root ngoài repository, chưa có lần chạy `eval/test2020`.

Xác nhận quyền đọc dữ liệu, nguồn gốc và độ sẵn sàng của snapshot bằng metadata/hash; không đánh giá nội dung trước claim. Môi trường chạy sẽ lưu `pip freeze` để audit. Credentials phải được cung cấp qua cơ chế vận hành được duyệt, không đặt trong execution metadata, exception message hoặc artifact chia sẻ. Failure message có lọc các dạng credential phổ biến và giới hạn 500 ký tự, nhưng không thay thế trách nhiệm giữ secret ngoài dữ liệu chẩn đoán.

## 6. IAM và phân quyền

Tuấn phối hợp cấu hình và xác minh quyền AWS/S3 theo yêu cầu nhóm. Runner cần `s3:PutObject` trên `eval/test2020/*` của bucket quy định; **không cấp `s3:DeleteObject` trên prefix này**. Conditional put dùng `IfNoneMatch="*"`, không phải upload ghi đè. Người chuẩn bị snapshot cần quyền đọc đúng object/version; nếu dùng local snapshot đã chuẩn bị, runner không tự tải snapshot thay thế.

Xác nhận credentials, bucket/prefix và quyền phù hợp trước cửa sổ chạy. Không thay IAM/CDK bằng gói sửa này; IAM thực cần được chủ sở hữu kiểm chứng riêng. Không xóa claim hoặc artifact để mở lại lượt chạy.

## 7. Claim và chạy chính thức

Chỉ chạy trong **16–22/11/2026** và sau khi nhóm cho phép, với toàn bộ điều kiện trên đã hoàn tất. Lệnh cho người vận hành (các đường dẫn minh họa phải được thay bằng file đã xác minh):

```text
python -m src.eval.run_test2020 --mode official --metadata <locked-metadata.json> --clean-dir <clean/prices/dt=DT> --output-root <outside-repository>
```

Thứ tự bắt buộc là Git preflight → xác thực config/protocol/provenance → conditional S3 claim → đọc và kiểm hash snapshot → giải mã/đánh giá. Claim local và claim S3 dùng cùng một bytes payload UTF-8 JSON deterministic, có đúng một LF cuối file. Không bypass claim; claim đã có hoặc conditional put thất bại thì không đọc snapshot và không chuyển sang overwrite.

Khi lỗi sau claim, giữ claim, lưu `failure.json` với loại lỗi, message đã lọc/giới hạn và trạng thái không tự retry. Không chạy lại, đổi seed, đổi dữ liệu hoặc xóa thư mục để thử tiếp. Báo nhóm và ghi quyết định theo §6 của kế hoạch trước bất kỳ hành động khắc phục nào. Lỗi trước claim không cho phép đọc test data và không được tạo claim chỉ để lưu lỗi. Sự tồn tại của claim có nghĩa đã đặt lượt chạy, không phải đã hoàn tất đánh giá.

## 8. Audit và bàn giao

Đối chiếu claim với runner commit, `origin_developer_sha`, snapshot DT/ba hash, lineage, protocol/config hash và môi trường. Kiểm tra local claim và started bytes khớp object S3; `checksums.json` băm bytes artifact thực, không tự băm chính nó. Dùng `verified_result()` kiểm tập file và hashes local; kiểm riêng bytes/checksums các object đã upload trước khi ghi nhận bàn giao hoàn tất. Nếu upload một phần thất bại, không suy đã có đầy đủ artifact và không tự rerun evaluation.

Review summary/report, counts và các lý do missing/excluded theo asset×h×sample; nhớ common mask test2020 theo từng horizon khác wrapper K3b yêu cầu đủ bảy horizon. S(a) vẫn cần đủ bảy skill. Primary block 20 giữ kiểm định centered bootstrap và Holm bốn tài sản; sensitivity block 10/40 chỉ có estimate/CI, không kết luận significance. Các nhóm DM gap bị chặn phải được báo đúng, không đổi policy để lấy p-value.

Ghi nhận kết quả kiểm chứng và trạng thái hoàn tất sau review, không chỉ dựa vào claim hoặc `started.json`. Không tự thay champion, chọn lại cấu hình hoặc diễn giải kết quả ngoài protocol. Thay champion sau thời gian đóng băng cần ADR mới theo kế hoạch.
