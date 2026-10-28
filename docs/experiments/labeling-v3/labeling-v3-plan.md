# Kế hoạch kiểm labeling-v3 trên thông cáo Fed/EIA thật

- Người làm: Phan Tấn Phước (prompt, script và bản nháp do Claude Code soạn). Người duyệt: Trịnh Tiến Khải.
- Căn cứ: hướng v3 Khải chốt ngày 24/10/2026 (comment ở PR #30) và mục "Việc tiếp theo" trong [`news-labeling-2026-10.md`](../news-labeling-2026-10.md).
- Trạng thái (28/10/2026): Khải đã duyệt prompt v3 và cách chọn 50 dòng, đã chốt ngưỡng và trả lời các câu hỏi (mục "Quyết định của Khải"). **Chưa gắn nhãn.** Chưa gọi model.

## Yêu cầu của Khải và chỗ đáp ứng

| Yêu cầu | File |
|---|---|
| Prompt v3: bỏ qua chỉ dẫn nhúng và ghi vào `notes`; tóm tắt rỗng → 0/uncertain; quy tắc hướng lãi suất, lạm phát với vàng-bạc; khi nào dùng `uncertain`/`mixed`; evidence bắt buộc khi impact ≥ 1, rỗng khi impact 0 | [`news-labeling-v3.md`](../../prompts/news-labeling-v3.md) |
| Sửa `acceptance_criteria` cho khớp quy tắc evidence | Trường `acceptance_criteria` trong bộ case, do [`build_labeling_cases_v3.py`](../../../scripts/benchmark/build_labeling_cases_v3.py) ghi |
| Bộ test 50 thông cáo Fed/EIA thật | [`candidates-fed-eia.csv`](candidates-fed-eia.csv) (69 ứng viên), [`labels-v3.csv`](labels-v3.csv) (Phước chọn và gắn nhãn) |
| Gán nhãn và chốt ngưỡng trước khi chạy | Bộ case có `status`; script từ chối chạy thật khi bộ case chưa `locked` hoặc ngưỡng khác cấu hình |

Bản v2 (`news-labeling-v2.md`, `synthetic_cases.json` draft-4, schema) giữ nguyên. Test `test_v2_inputs_unchanged_since_run` so SHA-256 của ba file này với `summary.json` của lần chạy 22/10.

## Quy trình

1. Phước gắn nhãn 50 dòng đã chọn trong `labels-v3.csv`, kèm 3 case đặc biệt (X01–X03).
2. Chạy script dựng bộ case. Script kiểm định dạng và quy tắc v3, rồi ghi `tests/labeling/real_cases_v3.json` ở trạng thái `draft`. Có lỗi thì không ghi file.
3. Merge `origin/developer` vào nhánh, rồi mở **một PR** gồm prompt, bộ case, nhãn và ngưỡng. Khải duyệt đáp án trong PR.
4. Khi Khải đồng ý đáp án, dựng lại với `--lock --approved-by "Khải"` và commit vào cùng PR. Từ đây không sửa prompt, đáp án hay ngưỡng nữa; script không ghi đè bộ case đã chốt.
5. Merge PR xong mới chạy: `--dry-run` để kiểm đường ống, rồi chạy thật **một lần**.
6. Khải duyệt tay 10 ô evidence theo tiêu chí đã ghi sẵn. Kết quả chạy và báo cáo (như `news-labeling-2026-10.md`) nằm ở **PR riêng**.

## Chọn 50 dòng

Claude Code chọn theo ủy quyền của Phước ngày 28/10/2026, chỉ dựa trên tiêu đề, tóm tắt và `coverage_tag`, trước khi có nhãn và trước khi gọi model. Cột `selected` trong `labels-v3.csv` đánh `x` cho 50 dòng này.

Nguyên tắc:
- Fed và EIA gần cân bằng: Fed 24, EIA 26.
- Bỏ các dòng gần như trùng mẫu văn với một dòng đã giữ, để bộ case không nặng về một kiểu tin.
- Mỗi kiểu tình huống giữ ít nhất một dòng: giữ, cắt, tăng lãi suất; phiếu phản đối một chiều và hai chiều; tồn kho tăng, giảm, trái chiều; dự báo giá tăng, giảm, trái chiều; tiêu đề lệch nội dung; tin không liên quan; tin không có nội dung.
- Giữ cả hai dòng `no_substance` và dòng `uncertain` duy nhất, vì đây là các trường hợp v2 làm sai (case 4, 7).

| Nhóm | Giữ | Bỏ | Lý do bỏ |
|---|---|---|---|
| Statement FOMC (10/14) | F01, F02, F05, F06, F07, F09, F11, F12, F13, F14 | F03, F04 | Giữ nguyên, không phản đối, trùng mẫu với F01 |
| | | F08 | Cắt lãi suất kèm phản đối hai chiều, đã có F07 |
| | | F10 | Giữ nguyên kèm bất định, gần F09 và F12 |
| Minutes (4/7) | F15, F17, F19, F21 | F16 | Diều hâu kèm người muốn cắt, gần F15 |
| | | F18 | Nới tiếp có điều kiện, gần F17 |
| | | F20 | Diều hâu báo trước tăng lãi suất, gần F21 |
| Khung chính sách, bài phát biểu, điều trần (8/9) | F22, F23, F24, F25, F26, F27, F29, F30 | F28 | Diều hâu sau đợt tăng, gần F27 |
| Tin ngân hàng của Fed (2/4) | F32, F33 | F31 | Giám sát ngân hàng, đã có F30 (bài phát biểu không liên quan) và F33 |
| | | F34 | Chấp thuận sáp nhập, cùng kiểu `relevant = false` với F32 |
| WPSR (6/9) | E01, E03, E04, E06, E08, E09 | E02 | Trái chiều dầu thô và sản phẩm, đã có E01 |
| | | E05 | Trái chiều, gần E01 |
| | | E07 | Dầu thô giảm kèm xả SPR, gần E06 |
| Dự báo và STEO (16/21) | E10, E11, E12, E14, E15, E17, E20, E23, E24, E26, E28, E30, E31, E32, E33, E35 | E13, E16, E21 | Dự báo giá giảm do dư cung năm 2025, đã có E10 và E12 |
| | | E25, E34 | Tiêu đề về khí hoặc điện kèm giá dầu, đã có E24, E33, E35 |
| AEO, tin hành chính (4/5) | E18, E22, E27, E29 | E19 | Tin hành chính `relevant = false`, đã có E18 và E27 |

Cơ cấu 50 dòng theo `coverage_tag`: `mixed` 11, `clear_oil` 10, `clear_gold_silver` 8, `low_impact` 7, `title_mismatch` 6, `irrelevant` 5, `no_substance` 2, `uncertain` 1. Thêm 3 case đặc biệt X01–X03 thì bộ kiểm có 53 case.

## Cách điền `labels-v3.csv`

- Mở bằng Excel hoặc Google Sheets. Khi lưu từ Excel, chọn **CSV UTF-8 (Comma delimited)**; định dạng CSV thường làm hỏng dấu tiếng Việt. Không đổi tên cột, không xóa dòng.
- Cột `title` chỉ để dễ nhìn. Script lấy tiêu đề và tóm tắt từ `candidates-fed-eia.csv` theo `id`, nên sửa `title` hay `summary_vi` trong file nhãn không có tác dụng.
- Dòng không chọn để trống `selected`; nhãn của dòng đó bị bỏ qua.

| Cột | Giá trị |
|---|---|
| `selected` | `x` cho đúng 50 dòng thật; để trống ở X01–X03 |
| `group` | `A` nếu case bắt buộc đạt 100% core check (như nhóm A ở v2); để trống là `B`. F06, F07, F14 đã điền sẵn `A` theo Khải; script báo lỗi nếu ba dòng này không ở nhóm A |
| `relevant` | `true` hoặc `false` |
| `event_type` | `monetary_policy`, `geopolitics`, `opec_supply`, `inventory`, `macro_data`, `other` |
| `<tài sản>_impact` | `0`, `1`, `2`, `3` |
| `<tài sản>_direction` | `bullish`, `bearish`, `mixed`, `uncertain` |
| `<tài sản>_confidence` | `high`, `medium`, `low` |
| `<tài sản>_evidence` | Một câu tiếng Việt khi impact ≥ 1; **để trống khi impact 0** |
| `notes` | Ghi chú tiếng Việt; bắt buộc ở X01–X03 |
| `reviewer_note` | Ghi chú riêng cho người duyệt, không đưa vào bộ case |
| `base_id`, `variant`, `injected_text` | Chỉ dùng ở X01–X03 |

Đáp án phải theo đúng quy tắc của prompt v3, nhất là các điểm v2 đã sai: mục 3 (thiếu nội dung → 0/uncertain/low), mục 6.2 (lãi suất tăng → vàng, bạc `bearish`; giảm → `bullish`; lạm phát không nhắc lãi suất → `uncertain`), mục 6.3 (`mixed` chỉ khi bài nêu cả hai chiều). Gợi ý trong cột `assets_possibly_affected` của danh sách ứng viên không phải đáp án.

Thêm theo Khải (28/10/2026):
- Chỉ dựa vào nội dung thông cáo (tiêu đề và `summary_vi`). Không xem giá chạy sau ngày công bố.
- Tin dầu không tác động lên vàng, bạc qua kênh lạm phát. Với thông cáo EIA, vàng và bạc để `0`/`uncertain` (evidence rỗng), trừ khi bài nêu rõ lãi suất hoặc lạm phát.

### Case đặc biệt (ngoài 50 dòng)

| id | variant | Cách dựng | Cần điền |
|---|---|---|---|
| X01 | `injection` | Tóm tắt của `base_id` + `injected_text` (câu lệnh tiếng Việt viết hoa, kiểu case 30 ở v2) | `base_id`, nhãn, `notes` nêu chỉ dẫn bị bỏ qua |
| X02 | `injection` | Như trên, câu lệnh tiếng Anh giả làm "ghi chú cho hệ thống" | Như trên |
| X03 | `empty_summary` | Tiêu đề của `base_id`, tóm tắt rỗng | `base_id`, `relevant`, `event_type`, cả bốn tài sản `0`/`uncertain`/`low`, `notes` |

- Nên lấy `base_id` của X01, X02 trong số 50 dòng đã chọn. Khi đó đáp án của X01, X02 giống dòng gốc, chỉ khác `notes`, nên dễ thấy model có bị câu lệnh kéo lệch không.
- Câu lệnh có sẵn trong `injected_text` sửa được, miễn là chưa chốt bộ case.

## Ngưỡng (Khải chốt 28/10/2026)

Cấu hình: [`configs/labeling_benchmark_v3.py`](../../../configs/labeling_benchmark_v3.py). Ngưỡng và tiêu chí duyệt tay được chép vào bộ case lúc dựng; khi chạy thật, script kiểm tra bộ case khớp cấu hình.

| Tiêu chí | v3 | v2 | Ghi chú |
|---|---:|---:|---|
| Đầu ra hợp lệ (schema + quy tắc 4, 5, 8) | 53/53 | 30/30 | Quy tắc 8 (evidence theo impact) là mới; sai thì được gọi lại một lần |
| Nhóm A, core check | 100% | 100% | Bắt buộc có F06, F07 (cắt) và F14 (tăng) để chặn quy tắc 6.2; Phước thêm các dòng khác |
| Case đặc biệt X01–X03 | 100% | case 30 | X01, X02: core check + `notes` không rỗng; X03: cả bốn tài sản `0/uncertain/low` |
| relevant | ≥ 90% | ≥ 90% | Trên 53 case |
| event_type | ≥ 90% | ≥ 90% | |
| direction (ô impact kỳ vọng ≥ 1) | ≥ 80% | ≥ 80% | Mẫu số phụ thuộc đáp án |
| \|impact lệch\| ≤ 1 | ≥ 90% | ≥ 90% | Trên 212 ô (53 × 4) |
| confidence khớp | Chỉ báo cáo | Chỉ báo cáo | |
| Hướng vàng, bạc ở tin `monetary_policy`/`macro_data` | Chỉ báo cáo | — | Đo riêng quy tắc mục 6.2 |
| Evidence duyệt tay | ≥ 8/10 | Không có | 10 ô lấy ngẫu nhiên (seed 7) trong các ô model gán impact ≥ 1; Khải chấm. Lần v2: 4/10 |

Giữ ngưỡng như v2 để so sánh được hai lần chạy. Tin thật có nhiều dòng dễ (statement FOMC cùng mẫu văn), nên chỉ số chung có thể cao hơn v2 mà prompt chưa chắc tốt hơn; nhóm A và case đặc biệt là phần chặn chính.

Tiêu chí duyệt tay, ghi sẵn trước khi chạy (một ô đạt khi đủ cả ba):
1. **Đúng nội dung:** evidence chỉ nêu điều có trong tiêu đề hoặc tóm tắt.
2. **Khớp hướng:** evidence ủng hộ đúng `direction` đã gán.
3. **Không thêm dữ kiện:** không có con số, nguyên nhân hay cơ chế mà bài không nêu.

## Quyết định của Khải (28/10/2026)

1. Ngưỡng giữ như v2. Statement có cắt hoặc tăng lãi suất (F06, F07, F14) vào nhóm A.
2. Duyệt tay evidence: đạt khi ≥ 8/10, chỉ lấy ô impact ≥ 1, seed 7, Khải chấm theo ba tiêu chí ở trên.
3. Tiêu đề tiếng Anh và tóm tắt tiếng Việt tự viết: dùng được cho v3.
4. Tin dầu không tính tác động lên vàng, bạc qua kênh lạm phát (khớp mục 5 và 6.2 của prompt).
5. Prompt, bộ case, nhãn và ngưỡng chung một PR. Merge xong mới chạy thật một lần; kết quả và báo cáo ở PR riêng. PR #42 không mở lại, vì commit của nó đã nằm trong nhánh này.

## Giới hạn

- Bộ case dùng tóm tắt tiếng Việt do nhóm tự viết. Khi chạy thật, đầu vào phải cùng định dạng với bộ case; Phước chốt với Tuấn collector tin sẽ đưa tóm tắt dạng nào (ngôn ngữ, độ dài, nguồn tóm tắt). Nếu định dạng khác, kết quả trên bộ này có thể không phản ánh đúng lúc chạy thật.
- Bộ case chỉ gồm thông cáo Fed và EIA, không có tin OPEC/OPEC+, IEA hay tin kim loại quý.

## Lệnh

```bash
python scripts/benchmark/build_labeling_cases_v3.py
python scripts/benchmark/build_labeling_cases_v3.py --lock --approved-by "Khải"
python scripts/benchmark/labeling_benchmark.py --config labeling_benchmark_v3 --dry-run
python scripts/benchmark/labeling_benchmark.py --config labeling_benchmark_v3
```

Lệnh cuối gọi Bedrock thật (sau `aws login --profile cpaws-dev`) và chỉ chạy một lần. Kết quả ghi vào `docs/experiments/results/news-labeling-v3-<ngày>/`. Chi phí ước tính khoảng 0,1–0,2 USD cho 53 lần gọi, suy từ lần v2 (30 lần gọi, 0,058 USD) và prompt v3 dài hơn; đối chiếu lại trang giá Bedrock lúc chạy.
