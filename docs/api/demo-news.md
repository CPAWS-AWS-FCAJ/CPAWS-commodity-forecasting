# Bộ tin demo cho tool `get_news`

Phương án dự phòng cho demo chatbot ngày 8/11/2026, dùng khi bảng DynamoDB `NewsLabels` chưa có dữ liệu thật ([contract](contract.md), mục `POST /chat`, phần "Nguồn dữ liệu của tool `get_news`").

- **File:** `gold.json`, `silver.json`, `brent.json`, `wti.json` trong [`infra/lambda/chat_api/news/`](../../infra/lambda/chat_api/news/). Mỗi file có dạng `{"asset": "...", "items": [...]}`, mỗi tin đúng 7 trường của contract.
- **Nguồn:** chỉ lấy thông cáo thật trên `federalreserve.gov` và `eia.gov`. Đã mở từng link và đối chiếu tiêu đề, ngày và nội dung.
- **Ngày tra:** 29/10/2026; tra lại ngày 5/11/2026 (thêm WPSR 4/11).
- **Gắn nhãn:** gắn tay theo bảng quy ước ở mục "Gắn nhãn" của [`labeling-v3-plan.md`](../experiments/labeling-v3/labeling-v3-plan.md) và các quy tắc của prompt [`news-labeling-v3.md`](../prompts/news-labeling-v3.md), giống nhãn tay trên production ([ADR-0013](../adr/0013-manual-news-labels-until-defense.md)). Chỉ theo nội dung thông cáo, không nhìn giá sau ngày công bố. Bản nháp ngày 29/10/2026; ngày 2/11/2026 sửa 2 nhãn cho đúng bảng quy ước (FOMC 28/10 và WPSR 21/10, Khải xác nhận cùng ngày).
- **Tóm tắt:** tiếng Việt, tự viết, 1–2 câu, không chép đoạn văn gốc. Tiêu đề giữ nguyên tiếng Anh như trang gốc. Riêng WPSR có thêm tuần dữ liệu trong ngoặc, giống `candidates-fed-eia.csv`.
- **Kiểm tra:** [`tests/test_demo_news.py`](../../tests/test_demo_news.py).

## Các tin trong bộ (tra ngày 29/10/2026, sửa nhãn ngày 2/11/2026, thêm WPSR 4/11 ngày 5/11/2026)

Mỗi bài có mặt ở cả 4 file, chỉ khác nhãn. Ký hiệu trong bảng: `2/bearish` nghĩa là `impact_score` 2, `direction` bearish; `0` nghĩa là 0/uncertain.

| `published_at` (UTC) | Bài | gold | silver | brent | wti |
|---|---|---|---|---|---|
| 2026-11-04T15:30:00Z | [WPSR, tuần kết thúc 30/10](https://www.eia.gov/petroleum/supply/weekly/archive/2026/2026_11_04/wpsr_2026_11_04.php) | 0 | 0 | 1/bullish | 1/bullish |
| 2026-10-28T18:00:00Z | [FOMC statement](https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm) | 1/bearish | 1/bearish | 0 | 0 |
| 2026-10-28T14:30:00Z | [WPSR, tuần kết thúc 23/10](https://www.eia.gov/petroleum/supply/weekly/archive/2026/2026_10_28/wpsr_2026_10_28.php) | 0 | 0 | 1/mixed | 1/mixed |
| 2026-10-21T14:30:00Z | [WPSR, tuần kết thúc 16/10](https://www.eia.gov/petroleum/supply/weekly/archive/2026/2026_10_21/wpsr_2026_10_21.php) | 0 | 0 | 1/mixed | 1/mixed |
| 2026-10-07T18:00:00Z | [Biên bản FOMC 15–16/9](https://www.federalreserve.gov/monetarypolicy/fomcminutes20260916.htm) | 2/bearish | 2/bearish | 0 | 0 |

Lý do gắn nhãn:

- **WPSR 4/11.** Dầu thô giảm 0,9 triệu thùng, xăng giảm 0,2 triệu thùng, nhiên liệu chưng cất giảm 3,6 triệu thùng; tổng tồn kho thương mại giảm 8,2 triệu thùng. Cả ba loại cùng giảm nên hỗ trợ giá dầu: bullish, giống E06 (dầu thô cũng chỉ giảm 0,9 triệu thùng). Mức là 1 theo bảng quy ước của plan, "tồn kho cùng chiều" chấm 1, chỉ chấm 2 khi dầu thô thay đổi trên 10 triệu thùng. Số liệu đã đối chiếu giữa trang WPSR, `summary.txt` và `table1.csv`.
- **FOMC 28/10.** Fed giữ lãi suất 3,75–4,00%, phiếu 10–2. Cook và Hammack phản đối vì muốn tăng 0,25 điểm %. Giữ nguyên lãi suất thì hướng đi theo tín hiệu về lộ trình lãi suất (v3 mục 6.2). Ở đây tín hiệu nghiêng về tăng nên vàng và bạc là bearish. Mức là 1 theo bảng quy ước của plan: giữ nguyên lãi suất có phiếu phản đối một chiều thì chấm 1, chỉ chấm 2 khi có ba phiếu muốn tăng (như F13 ngày 29/7, phiếu 9–3). Kỳ này có hai phiếu. Bản 29/10 chấm 2, sửa ngày 2/11. Dầu để 0 vì thông cáo không nhắc tới cung cầu dầu.
- **Biên bản FOMC 15–16/9.** Đa số thành viên cho rằng nhiều khả năng cần tăng thêm trước cuối năm, nên vàng và bạc là 2/bearish (giống F21). Biên bản có nhắc giá năng lượng nhưng chỉ coi đó là nguyên nhân gây lạm phát, không nêu yếu tố cung cầu dầu, nên dầu để 0 (giống ghi chú ở F27).
- **WPSR 28/10.** Tồn kho dầu thô giảm 1,9 triệu thùng (hỗ trợ giá), nhưng tồn kho xăng tăng 3,9 triệu thùng (gây áp lực giảm giá), và bài không nói yếu tố nào chiếm ưu thế. Vì vậy chấm 1/mixed (v3 mục 6.3, giống E08/E09).
- **WPSR 21/10.** Dầu thô giảm 3,1 triệu thùng và xăng giảm 3,0 triệu thùng, nhưng nhiên liệu chưng cất tăng 1,7 triệu thùng. Bảng quy ước của plan chấm "dầu thô và sản phẩm trái chiều" là 1/mixed (như E01, E08), kể cả khi tổng tồn kho thương mại giảm 8,5 triệu thùng. Không giống E06, vì ở E06 cả ba loại cùng giảm. Bản 29/10 chấm 1/bullish vì tổng tồn kho giảm, sửa ngày 2/11.
- Tin EIA chấm vàng và bạc 0/uncertain; tin Fed chấm dầu 0/uncertain. Quy ước này theo v3 và được test kiểm.

Về giờ đăng:

- Giờ của thông cáo Fed lấy từ RSS của Fed (`pubDate`, GMT).
- Trang WPSR không ghi giờ đăng của từng kỳ. Giờ ở đây là giờ phát hành theo lịch của EIA, 10:30 sáng giờ miền Đông Mỹ, quy sang UTC: `14:30:00Z` khi còn giờ mùa hè (EDT), `15:30:00Z` từ 1/11/2026 (EST).
- Kỳ 4/11/2026 lên trang trễ so với lịch: lúc 15:33Z và 16:10Z ngày 4/11 trang và file số liệu vẫn trả 404, đến 01:58Z ngày 5/11 mới có. Trang ghi "Release Date: November 4, 2026", nên `published_at` vẫn để giờ theo lịch.

## Lưu ý: khoảng ngày lúc demo

Khi model không truyền ngày, `get_news` lấy từ `to_date − 7 ngày` đến hôm nay theo giờ Việt Nam, với `min_impact = 2`. Hôm demo 8/11/2026 khoảng này là **1/11–8/11**. Trong khoảng đó bộ tin chỉ có WPSR 4/11, ở mức 1, nên với `min_impact = 2` mặc định `get_news` vẫn trả rỗng cho cả 4 tài sản. Từ 28/10 trở đi không có tin nào đạt mức 2. Không đổi ngày đăng để tin lọt vào khoảng mặc định, vì như vậy là sai sự thật.

Câu hỏi không nêu ngày sẽ nhận kết quả rỗng, và chatbot sẽ nói không tìm thấy tin đáng kể. Cách xử lý:

1. **Đã làm mới bộ tin ngày 5/11** (hạn 6/11), theo mục bên dưới. Tiến deploy lại `CpawsApi` ngày 7/11, vì bộ tin nằm trong asset Lambda. Phạm vi tin giống nhãn tay trên production (ADR-0013): với Fed chỉ lấy FOMC statement và biên bản FOMC; với EIA lấy WPSR, STEO và bài dự báo. Kết quả tra ngày 5/11:
   - EIA: thêm WPSR 4/11 (tuần kết thúc 30/10), 1/bullish cho dầu. STEO tháng 11 ra ngày 10/11, sau ngày demo.
   - Fed: RSS không có FOMC statement hay biên bản mới. Biên bản kỳ họp 27–28/10 ra ngày 18/11, sau ngày demo. SLOOS (2/11) và bài phát biểu nằm ngoài phạm vi của ADR-0013 nên không thêm.
2. **Câu hỏi demo nêu rõ khoảng ngày**, như câu 3 trong kịch bản demo (PR #77): "Vì sao vàng có thể biến động thời gian gần đây? Xem giúp mình các tin tức từ 7/10/2026 tới nay.". Khi đó model truyền `from_date` và lấy được biên bản FOMC đăng 7/10 (mức 2). Từ khi FOMC 28/10 hạ xuống mức 1 (ngày 2/11), vàng và bạc chỉ còn biên bản này đạt mức 2, nên câu hỏi "từ 28/10 tới nay" ở `min_impact = 2` không ra tin vàng, bạc nào. Sau khi Tiến deploy lại, hỏi đúng câu này trên AWS: `get_news` phải trả ít nhất 1 tin (Khải, 2/11).
3. **WPSR thường chỉ đạt mức 1**, nên bị lọc ở `min_impact = 2` mặc định. Brent và WTI hiện không có tin nào đạt mức 2; nếu model truyền `min_impact = 1` thì khoảng mặc định ngày 8/11 ra WPSR 4/11. Giữ ngưỡng 2 (Tiến, Khải 2/11); kịch bản có một câu tin dầu để cho thấy chatbot nói "không có tin đáng kể". Không nâng điểm chỉ để tin hiện ra.
4. Đề xuất code (chưa làm, cần sửa `src/chatbot/news.py` và contract): thêm biến môi trường số ngày mặc định, ví dụ `NEWS_DEFAULT_DAYS`, để nới khoảng ngày khi demo.

## Cách làm mới trước demo

1. Tra thông cáo mới trên trang chính thức:
   - Fed: RSS `https://www.federalreserve.gov/feeds/press_all.xml` và `https://www.federalreserve.gov/feeds/speeches.xml`;
   - EIA: thư mục lưu trữ WPSR `https://www.eia.gov/petroleum/supply/weekly/archive/2026/<YYYY_MM_DD>/wpsr_<YYYY_MM_DD>.php`; số liệu lấy từ `download/summary.txt` và `download/table1.csv` trong cùng thư mục.
2. Mở từng link, đối chiếu tiêu đề, ngày và số liệu. Không thêm bài có link hoặc ngày chưa kiểm được.
3. Thêm bài vào **cả 4 file** trong `infra/lambda/chat_api/news/`. Giữ nguyên `title`, `summary`, `link`, `source`, `published_at` giữa các file, chỉ đổi `impact_score` và `direction` theo từng tài sản (theo bảng quy ước của plan). Tóm tắt tối đa 300 ký tự (ADR-0013). Sắp tin mới trước.
4. Mỗi file tối đa 10 tin (`MAX_ITEMS`). Khi đầy, bỏ tin cũ nhất.
5. Cập nhật bảng ở mục trên và ngày tra trong file này.
6. Chạy test:

   ```bash
   python -m pytest tests/test_demo_news.py -q
   ```

## Cách bật trên Lambda chat

- Bỏ `NEWS_TABLE_NAME` khỏi cấu hình Lambda. Khi biến này có giá trị, Lambda đọc bảng và bỏ qua `NEWS_DIR`, không tự chuyển nguồn.
- Đặt `NEWS_DIR=/var/task/news`.
- 4 file `.json` được đóng gói vào thư mục `news/` ở gốc asset Lambda, cạnh `handler.py`: [`infra/stacks/chat_asset.py`](../../infra/stacks/chat_asset.py) chép đúng 4 file này (PR #63). Không đổi tên file, vì test kiểm mọi `news/*.json` đều có trong danh sách đó.
- Khi collector đã có dữ liệu thật: đặt lại `NEWS_TABLE_NAME` (có thể giữ `NEWS_DIR`, vì nó bị bỏ qua).

Chạy thử ở máy cục bộ (Git Bash):

```bash
python -c "from src.chatbot import news as N; print(N.get_news({'asset': 'gold', 'from_date': '2026-10-01'}, N.JsonFileNewsRepository('infra/lambda/chat_api/news')))"
```
