# Roll của CL=F, BZ=F và đợt WTI lệch RWTC 9–10/2026

- Người làm: Trịnh Tiến Khải (script và bản nháp do Claude Code soạn), 12/10/2026. Người đọc: Nguyễn Tiến Long (buổi chốt target, hạn 16/10).
- Script: `scripts/roll_analysis.py` (chỉ đọc dữ liệu). Đầu vào: bản clean `dt=2026-10-09` (giá tới 08/10/2026; RWTC, RBRTE tới 06/10/2026) và file thô yfinance `raw/yfinance/dt=2026-10-08` (lấy volume).
- Return là log return ngày, tính theo **dòng giá liên tiếp của từng tài sản**, đơn vị %. CL=F và BZ=F cùng chốt lúc 14:30 ET.
- Phần 1 dùng dữ liệu 2026, chỉ để kiểm tra chất lượng dữ liệu. Phần 2 **chỉ dùng 2014–2019**: dữ liệu được cắt tại 31/12/2019 ngay khi đọc. Riêng phần kiểm chứng ngày chuyển giá (mục 2.1) có dẫn thêm hai lần roll năm 2026, chỉ để kiểm tra chất lượng dữ liệu.

## 1. Đợt CL=F thấp hơn RWTC khoảng 7% từ 29/9/2026: lỗi ở CL=F hay ở RWTC?

"Lệch so với trung vị 60" là giá trị trừ đi trung vị của chính nó trong 60 phiên chung trước đó (chỉ nhìn lùi), đơn vị điểm %.

| Ngày | r CL=F | r BZ=F | r CL − r BZ | Chênh lệch Brent–WTI, lệch so với trung vị 60 | CL=F/RWTC, lệch so với trung vị 60 | r RWTC | r CL − r RWTC |
|---|---|---|---|---|---|---|---|
| 22/9 | −1,25 | −1,09 | −0,16 | −1,46 | −0,41 | −0,58 | −0,67 |
| **23/9 (CL roll)** | −2,60 | +3,79 | **−6,39** | **+4,92** | +0,18 | −3,19 | +0,59 |
| 24/9 | +2,62 | +3,36 | −0,73 | +5,58 | +0,15 | +2,64 | −0,02 |
| 25/9 | −2,35 | −2,16 | −0,19 | +5,69 | (RWTC lỗi đã biết) | — | — |
| 28/9 | +0,21 | +0,92 | −0,71 | +6,34 | (RWTC lỗi đã biết) | — | — |
| **29/9** | −3,54 | −2,59 | −0,95 | +7,28 | **−5,84** | **+0,29** | **−5,98** |
| 30/9 | +1,16 | +0,91 | +0,24 | +7,02 | −5,74 | +1,06 | +0,10 |
| **1/10 (BZ roll)** | +2,67 | −1,19 | **+3,86** | +3,14 | −5,69 | +2,63 | +0,04 |
| 2/10 | −1,91 | −0,06 | −1,85 | +4,97 | −5,71 | −1,90 | −0,01 |
| 5/10 | −1,86 | −1,91 | +0,04 | +4,91 | −5,75 | −1,81 | −0,05 |
| 6/10 | +0,01 | +0,26 | −0,25 | +5,16 | −5,85 | +0,11 | −0,10 |
| 7/10 | −1,31 | −0,38 | −0,93 | +6,07 | (RWTC chưa công bố) | — | — |
| 8/10 | +3,57 | +3,99 | −0,42 | +6,47 | (RWTC chưa công bố) | — | — |

Phiên 9/10 chưa có trong bản clean của repo, nên không có trong bảng.

**Kết luận: đợt lệch nằm ở phía RWTC, không phải lỗi dữ liệu của CL=F.**
- Ngày 29/9, CL=F (−3,54%) và BZ=F (−2,59%) cùng giảm. Phần chênh −0,95 điểm nằm trong mức bình thường (p90 của |r CL − r BZ| ngày thường năm 2019 là 0,87; năm 2014–2018 là 1,39). RWTC lại tăng +0,29%, tách khỏi cả hai hợp đồng tương lai. Toàn bộ đợt lệch khoảng 6% xuất hiện trong đúng một phiên, ngay sau hai ngày RWTC có lỗi đã biết (25 và 28/9). Từ 30/9, return của CL=F và RWTC lại khớp nhau (chênh dưới 0,1 điểm), nên đây là một bước dịch mức của RWTC chứ không phải nhiễu ngày.
- Ngày 23/9 (CL roll), CL=F lệch −6,4% so với BZ=F. Đây là khoảng cách roll khi thị trường backwardation mạnh: hợp đồng mới rẻ hơn hợp đồng cũ. RWTC cũng giảm theo (−3,19%), nên tỷ số CL=F/RWTC không đổi trong ngày này. Ngày 1/10 (BZ roll) có hiện tượng tương tự theo chiều ngược lại (+3,86%).
- RBRTE so với BZ=F dao động rất mạnh (lệch −7 đến −24 điểm so với trung vị 60 phiên). Như vậy chuỗi giao ngay của EIA năm 2026 lệch xa hợp đồng tương lai ở cả Brent lẫn WTI, đúng với cảnh báo trong ADR-0005 rằng chính chuỗi giao ngay của EIA cũng nhiễu.
- **Hệ quả:** giữ CL=F; không sửa dữ liệu. `xcheck_level` vẫn chỉ đánh dấu (ADR-0005). Nên xem lại RWTC sau lần EIA cập nhật tuần tới; nếu EIA sửa số liệu cuối tháng 9 thì cờ của đợt này sẽ tự mất.

## 2. Roll của CL=F và BZ=F, 2014–2019

### 2.1 Ngày roll theo quy tắc so với ngày Yahoo thực sự chuyển hợp đồng

- Ngày roll theo quy tắc (`flag=roll`) là phiên đầu tiên sau ngày đáo hạn: quy tắc CL cho WTI, quy tắc ICE Brent cho BZ (`calendars.roll_days`).
- Ngày Yahoo thực sự chuyển hợp đồng được nhận biết theo hai cách, trong ±3 phiên quanh ngày roll:
  - (a) phiên có volume tăng mạnh nhất, vì hợp đồng mới có volume lớn hơn hẳn hợp đồng sắp đáo hạn;
  - (b) phiên có |r CL − r BZ| lớn nhất.

| | CL=F (72 lần roll) | BZ=F (72 lần roll) |
|---|---|---|
| Volume: lệch so với ngày theo quy tắc | **−1 phiên: 72/72** | 0: 50; −1: 19; ±2 hoặc +1: 3 |
| Mức tăng volume ở ngày được nhận ra (trung vị) | ×4,3 | ×22 |
| Khoảng cách với phiên tăng lớn thứ hai (trung vị, log) | 1,16 (khoảng ×3) | 2,84 (khoảng ×17) |
| Phần dư giá: lệch so với ngày theo quy tắc | rải từ −3 đến +3 (0: 31/72) | rải từ −3 đến +3 (0: 26/72, +1: 24/72) |
| Cách (a) và (b) chọn cùng một ngày | 4/72 | 16/72 |
| Phiên volume bằng 0 hoặc thiếu | 0 | 6 |

- **CL=F: volume của Yahoo chuyển sang hợp đồng mới vào chính ngày đáo hạn, sớm hơn cờ `roll` đúng 1 phiên, ở cả 72/72 lần.** Tín hiệu rất rõ (volume tăng khoảng 4 lần, lớn hơn khoảng 3 lần so với phiên tăng thứ hai). Tuy vậy, **volume chuyển sớm không có nghĩa là giá đóng cửa chuyển sớm**:
  - Ở hai lần roll năm 2026, volume cũng nhảy vào ngày đáo hạn (21/4: ×3,3; 22/9: ×5,5).
  - Nhưng khoảng cách giá xuất hiện ở phiên sau, đúng ngày có cờ `roll`. Ngày 23/9/2026, r CL − r BZ = −6,4%, trong khi ngày đáo hạn 22/9 chỉ là −0,16% (bảng ở mục 1).
  - Giải thích hợp lý: vào ngày đáo hạn, Yahoo báo volume của hợp đồng mới nhưng giá đóng cửa vẫn là settlement của hợp đồng cũ.
  - Kết luận: **cờ `roll` hiện tại khớp với ngày giá chuyển hợp đồng**. Volume chỉ cho biết ngày đáo hạn một cách tin cậy, không dùng để định ngày khoảng cách giá. Trong 2014–2019, khoảng cách roll của CL quá nhỏ để kiểm chứng bằng giá (mục 2.2); chỉ có hai lần roll năm 2026 làm bằng chứng.
- **BZ=F**: cờ khớp ngày chuyển thật ở 50/72 lần, sớm hơn 1 phiên ở 19/72 lần. Volume của BZ=F trong 2014–2018 rất nhỏ, nên tỷ lệ tăng lớn (×22) nhưng có 6 phiên volume bằng 0.
- **Phần dư giá không nhận ra ngày chuyển một cách tin cậy trong 2014–2019**: kết quả rải đều từ −3 đến +3 và hiếm khi trùng với volume. Lý do: khoảng cách roll khi đó nhỏ so với dao động ngày (xem 2.2). Khi khoảng cách roll lớn (thị trường backwardation mạnh như 9/2026) thì phần dư giá nhận ra đúng ngày.
- **Trả lời câu hỏi "có nhận ra ngày chuyển thật một cách tin cậy không"**: ngày đáo hạn thì có (volume, 72/72). Ngày giá chuyển thì chỉ chắc chắn khi khoảng cách roll lớn; bằng chứng 2026 cho thấy nó trùng cờ `roll`. Vì vậy **chưa nên sửa quy tắc cờ `roll`**.
- Đợt CL=F/RWTC lệch 23–28/4/2026 bắt đầu sau cờ `roll` 22/4 một phiên. Vì RWTC cũng là một chuỗi tham chiếu nhiễu (mục 1), điều này chưa đủ để kết luận về ngày chuyển giá của CL=F.

### 2.2 Độ lớn |return| ngày roll so với ngày thường

Ngày thường là ngày không phải roll của cả hai hợp đồng, theo cả quy tắc lẫn volume. Đơn vị %.

| Tài sản | Giai đoạn | Ngày thường: trung vị / p90 (n) | Ngày roll theo quy tắc: trung vị / p90 (n) | Ngày chuyển theo volume: trung vị / p90 (n) |
|---|---|---|---|---|
| WTI | 2014–2018 | 1,20 / 3,71 (1064) | 1,46 / 3,72 (60) | 0,90 / 3,73 (60) |
| WTI | 2019 | 1,02 / 3,14 (206) | 1,08 / 2,54 (12) | 1,41 / 3,31 (12) |
| Brent | 2014–2018 | 1,04 / 3,55 (1063) | **0,06 / 1,31 (60)** | **0,06 / 1,05 (61)** |
| Brent | 2019 | 0,97 / 2,68 (206) | **2,33 / 4,96 (12)** | 0,84 / 2,58 (11) |

- **WTI**: |return| ngày roll gần như bằng ngày thường. Trong 2014–2019, khoảng cách roll của CL nhỏ so với dao động ngày.
- **Brent 2014–2018**: ngày roll có |return| gần bằng 0 (trung vị 0,06%). BZ=F ít giao dịch quanh ngày chuyển hợp đồng nên giá đứng (khớp với cờ `low_liquidity` trong ADR-0005), và biến động thật dồn sang phiên kế bên.
- **Brent 2019**: ngày roll theo quy tắc có |return| gấp khoảng 2,4 lần ngày thường. Đây là khoảng cách roll thật, khi BZ=F đã giao dịch nhiều hơn.

### 2.3 CL và BZ có roll cùng ngày không

- Không có ngày nào hai hợp đồng cùng roll theo quy tắc. Có 2 lần roll cách nhau 1 ngày.
- Theo volume, không có ngày chuyển hợp đồng nào trùng nhau.
- Vì vậy, vào ngày một hợp đồng roll, hợp đồng kia luôn có return "sạch" để dùng thay.

### 2.4 Thay return ngày roll của CL bằng return BZ cùng ngày (và ngược lại)

Sai số của việc thay thế được ước lượng trên **ngày không roll** (|r CL − r BZ|, điểm %). Mốc so sánh là thay bằng 0 (sai số = |r| của chính tài sản).

| Giai đoạn | n ngày | Tương quan r CL ~ r BZ | Sai số thay thế: MAE / trung vị / p90 / RMSE | Mốc thay bằng 0: MAE CL / BZ |
|---|---|---|---|---|
| 2014–2018 | 1063 | 0,916 | 0,62 / 0,41 / 1,39 / 0,93 | 1,66 / 1,58 |
| 2019 | 206 | 0,955 | 0,45 / 0,38 / 0,87 / 0,60 | 1,40 / 1,31 |

Thêm để tham khảo: |r CL − r BZ| ngay trên ngày roll (theo quy tắc hoặc theo volume):

| Giai đoạn | Ngày roll của CL: trung vị / trung bình | Ngày roll của BZ: trung vị / trung bình |
|---|---|---|
| 2014–2018 | 0,59 / 1,04 | 1,08 / 1,50 |
| 2019 | 0,31 / 0,48 | 1,49 / 1,66 |

**Đọc kết quả:**
- Thay bằng return của hợp đồng kia có sai số khoảng **0,45–0,62 điểm % MAE**, chỉ bằng khoảng 1/3 so với thay bằng 0, vì tương quan rất cao (0,92–0,96).
- Ngày roll của CL: chênh lệch chỉ lớn hơn ngày thường một chút (0,48 so với 0,45 năm 2019), vì khoảng cách roll của CL trong 2014–2019 nhỏ. Thay hay không thay khác nhau không đáng kể.
- Ngày roll của BZ: chênh lệch gấp 2,4–3,7 lần ngày thường. Đây là chỗ việc thay thế (hoặc xử lý khác) có tác dụng. Tuy vậy, trong 2014–2018 sự sai lệch của BZ nằm ở **giá đứng quanh ngày roll**, không chỉ ở một ngày, nên thay đúng một ngày có thể vẫn bỏ sót phiên kế bên.

## Đầu vào cho buổi chốt target với Long (16/10)

Các phương án xử lý return ngày roll trong target (chưa quyết định; quyết định ghi vào ADR-0008):

1. **Giữ nguyên** (target là return của chuỗi Yahoo như hiện có). Đơn giản. Với WTI 2014–2019 ảnh hưởng nhỏ. Với Brent 2014–2018 có nhiễu quanh roll. Với 2026, khoảng cách roll đã lên tới khoảng 4–6%, nên trên tập test cần biết ngày nào là roll.
2. **Thay return ngày roll bằng return của hợp đồng kia** (sai số ước lượng khoảng 0,5–0,6 điểm % MAE). Dùng cờ `roll` hiện tại (khớp ngày giá chuyển theo bằng chứng 2026). Không dùng ngày volume nhảy, vì đó là ngày đáo hạn và sớm hơn một phiên. Với Brent 2014–2018 có thể phải thay cả phiên kế bên vì giá đứng quanh ngày roll.
3. **Loại các ngày gốc có cửa sổ target chứa ngày roll**. Với h = 1 thì mất khoảng 5% số mẫu, nhưng với h = 7 thì mất khoảng 1/3, nên tốn kém.
4. **Chuỗi back-adjusted** (ADR-0005 đang không dùng). Nhắc lại để đầy đủ.

Việc cần làm trước buổi họp: thống nhất với Long rằng "ngày roll" là ngày giá chuyển (cờ `roll`), không phải ngày volume nhảy. Nếu cần chắc hơn, so thêm các lần roll năm 2020–2026 có khoảng cách lớn. Đây là kiểm tra chất lượng dữ liệu, không phải đánh giá mô hình trên tập test.
