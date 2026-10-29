# Bộ tin demo cho tool `get_news`

Phương án dự phòng cho demo chatbot ngày 8/11/2026, dùng khi bảng DynamoDB `NewsLabels` chưa có dữ liệu thật ([contract](contract.md), mục `POST /chat`, phần "Nguồn dữ liệu của tool `get_news`").

- **File:** `gold.json`, `silver.json`, `brent.json`, `wti.json` trong [`infra/lambda/chat_api/news/`](../../infra/lambda/chat_api/news/). Mỗi file có dạng `{"asset": "...", "items": [...]}`, mỗi tin đúng 7 trường của contract.
- **Nguồn:** chỉ lấy thông cáo thật trên `federalreserve.gov` và `eia.gov`. Đã mở từng link và đối chiếu tiêu đề, ngày và nội dung.
- **Ngày tra:** 29/10/2026.
- **Gắn nhãn:** bản nháp ngày 29/10/2026 theo quy ước của prompt `labeling-v3` (`docs/prompts/news-labeling-v3.md` trên nhánh `exp/labeling-v3-candidates`). Phước soát lại nhãn trước khi merge.
- **Tóm tắt:** tiếng Việt, tự viết, 1–2 câu, không chép đoạn văn gốc. Tiêu đề giữ nguyên tiếng Anh như trang gốc. Riêng WPSR có thêm tuần dữ liệu trong ngoặc, giống `candidates-fed-eia.csv`.
- **Kiểm tra:** [`tests/test_demo_news.py`](../../tests/test_demo_news.py).

## Các tin trong bộ (bản ngày 29/10/2026)

Mỗi bài có mặt ở cả 4 file, chỉ khác nhãn. Ký hiệu trong bảng: `2/bearish` nghĩa là `impact_score` 2, `direction` bearish; `0` nghĩa là 0/uncertain.

| `published_at` (UTC) | Bài | gold | silver | brent | wti |
|---|---|---|---|---|---|
| 2026-10-28T18:00:00Z | [FOMC statement](https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm) | 2/bearish | 2/bearish | 0 | 0 |
| 2026-10-28T14:30:00Z | [WPSR, tuần kết thúc 23/10](https://www.eia.gov/petroleum/supply/weekly/archive/2026/2026_10_28/wpsr_2026_10_28.php) | 0 | 0 | 1/mixed | 1/mixed |
| 2026-10-21T14:30:00Z | [WPSR, tuần kết thúc 16/10](https://www.eia.gov/petroleum/supply/weekly/archive/2026/2026_10_21/wpsr_2026_10_21.php) | 0 | 0 | 1/bullish | 1/bullish |
| 2026-10-07T18:00:00Z | [Biên bản FOMC 15–16/9](https://www.federalreserve.gov/monetarypolicy/fomcminutes20260916.htm) | 2/bearish | 2/bearish | 0 | 0 |

Lý do gắn nhãn:

- **FOMC 28/10.** Fed giữ lãi suất 3,75–4,00%, phiếu 10–2. Cook và Hammack phản đối vì muốn tăng 0,25 điểm %. Giữ nguyên lãi suất thì hướng đi theo tín hiệu về lộ trình lãi suất (v3 mục 6.2). Ở đây tín hiệu nghiêng về tăng nên vàng và bạc là bearish, cùng mức với kỳ 29/7/2026 trong `labels-v3.csv` (F13). Dầu để 0 vì thông cáo không nhắc tới cung cầu dầu.
- **Biên bản FOMC 15–16/9.** Đa số thành viên cho rằng nhiều khả năng cần tăng thêm trước cuối năm, nên vàng và bạc là 2/bearish (giống F21). Biên bản có nhắc giá năng lượng nhưng chỉ coi đó là nguyên nhân gây lạm phát, không nêu yếu tố cung cầu dầu, nên dầu để 0 (giống ghi chú ở F27).
- **WPSR 28/10.** Tồn kho dầu thô giảm 1,9 triệu thùng (hỗ trợ giá), nhưng tồn kho xăng tăng 3,9 triệu thùng (gây áp lực giảm giá), và bài không nói yếu tố nào chiếm ưu thế. Vì vậy chấm 1/mixed (v3 mục 6.3, giống E08/E09).
- **WPSR 21/10.** Dầu thô và xăng cùng giảm, tổng tồn kho thương mại giảm 8,5 triệu thùng. Nhiên liệu chưng cất tăng nhẹ 1,7 triệu thùng nhưng bài cho biết tổng giảm, nên chấm 1/bullish (giống E06).
- Tin EIA chấm vàng và bạc 0/uncertain; tin Fed chấm dầu 0/uncertain. Quy ước này theo v3 và được test kiểm.

Về giờ đăng:

- Giờ của thông cáo Fed lấy từ RSS của Fed (`pubDate`, GMT).
- Trang WPSR không ghi giờ đăng của từng kỳ. Giờ ở đây là giờ phát hành theo lịch của EIA, 10:30 sáng giờ miền Đông Mỹ, quy sang UTC: `14:30:00Z` khi còn giờ mùa hè (EDT), `15:30:00Z` từ 1/11/2026 (EST).

## Lưu ý: khoảng ngày lúc demo

Khi model không truyền ngày, `get_news` lấy từ `to_date − 7 ngày` đến hôm nay theo giờ Việt Nam, với `min_impact = 2`. Hôm demo 8/11/2026 khoảng này là **1/11–8/11**. Bộ tin hiện tại (tra ngày 29/10) **không có tin nào trong khoảng đó**: thông cáo mới nhất là FOMC 28/10. Không đổi ngày đăng để tin lọt vào khoảng mặc định, vì như vậy là sai sự thật.

Nếu không làm mới, `get_news` sẽ trả rỗng cho câu hỏi không nêu ngày, và chatbot sẽ nói không tìm thấy tin đáng kể. Cách xử lý:

1. **Làm mới bộ tin ngày 6 hoặc 7/11** (cách đề xuất), theo mục bên dưới. Các tin dự kiến có trong khoảng 1–8/11, theo lịch tra ngày 29/10:
   - Fed: Senior Loan Officer Opinion Survey ngày 2/11, cùng các bài phát biểu Fed công bố sau ngày 29/10. Thường chỉ bài phát biểu nói về lãi suất mới đạt mức 2 với vàng và bạc. SLOOS là khảo sát tín dụng ngân hàng, khả năng cao chấm 0–1.
   - EIA: WPSR ngày 4/11 (tuần kết thúc 30/10, khoảng 15:30:00Z). STEO tháng 11 ra ngày 10/11, sau ngày demo.
   - Biên bản kỳ họp FOMC 27–28/10 thường ra khoảng 3 tuần sau kỳ họp, sau ngày demo.
2. **Câu hỏi demo nêu rõ khoảng ngày**, ví dụ "Tin tức từ 28/10 tới nay ảnh hưởng thế nào tới giá vàng?". Khi đó model truyền `from_date` và lấy được FOMC 28/10.
3. **WPSR thường chỉ đạt mức 1**, nên bị lọc ở `min_impact = 2` mặc định. Muốn demo tin dầu thì hỏi rõ cả tin ít tác động, hoặc chấp nhận câu trả lời "không có tin đáng kể". Không nâng điểm chỉ để tin hiện ra.
4. Đề xuất code (chưa làm, cần sửa `src/chatbot/news.py` và contract): thêm biến môi trường số ngày mặc định, ví dụ `NEWS_DEFAULT_DAYS`, để nới khoảng ngày khi demo.

## Cách làm mới trước demo

1. Tra thông cáo mới trên trang chính thức:
   - Fed: RSS `https://www.federalreserve.gov/feeds/press_all.xml` và `https://www.federalreserve.gov/feeds/speeches.xml`;
   - EIA: thư mục lưu trữ WPSR `https://www.eia.gov/petroleum/supply/weekly/archive/2026/<YYYY_MM_DD>/wpsr_<YYYY_MM_DD>.php`; số liệu lấy từ `download/summary.txt` và `download/table1.csv` trong cùng thư mục.
2. Mở từng link, đối chiếu tiêu đề, ngày và số liệu. Không thêm bài có link hoặc ngày chưa kiểm được.
3. Thêm bài vào **cả 4 file** trong `infra/lambda/chat_api/news/`. Giữ nguyên `title`, `summary`, `link`, `source`, `published_at` giữa các file, chỉ đổi `impact_score` và `direction` theo từng tài sản (theo v3). Sắp tin mới trước.
4. Mỗi file tối đa 10 tin (`MAX_ITEMS`). Khi đầy, bỏ tin cũ nhất.
5. Cập nhật bảng ở mục trên và ngày tra trong file này.
6. Chạy test:

   ```bash
   python -m pytest tests/test_demo_news.py -q
   ```

## Cách bật trên Lambda chat

- Bỏ `NEWS_TABLE_NAME` khỏi cấu hình Lambda. Khi biến này có giá trị, Lambda đọc bảng và bỏ qua `NEWS_DIR`, không tự chuyển nguồn.
- Đặt `NEWS_DIR=/var/task/news`.
- Đóng gói 4 file `.json` vào thư mục `news/` ở gốc asset Lambda, cạnh `handler.py`. Nếu asset là thư mục `infra/lambda/chat_api/` thì thư mục `news/` đã nằm đúng chỗ. Nếu bundling chỉ chép từng file, cần thêm bước chép `infra/lambda/chat_api/news/*.json` (Tiến chốt bundling).
- Khi collector đã có dữ liệu thật: đặt lại `NEWS_TABLE_NAME` (có thể giữ `NEWS_DIR`, vì nó bị bỏ qua).

Chạy thử ở máy cục bộ (Git Bash):

```bash
python -c "from src.chatbot import news as N; print(N.get_news({'asset': 'gold', 'from_date': '2026-10-01'}, N.JsonFileNewsRepository('infra/lambda/chat_api/news')))"
```
