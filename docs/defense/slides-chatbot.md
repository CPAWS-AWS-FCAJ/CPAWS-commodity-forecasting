---
marp: true
theme: default
paginate: true
size: 16:9
title: CPAWS chatbot, báo cáo cuối kỳ
style: |
  section { font-size: 26px; }
  h1 { font-size: 40px; }
  table { font-size: 22px; }
  pre { font-size: 19px; line-height: 1.35; }
  .small { font-size: 18px; color: #555; }
---

<!--
Slide chương Chatbot cho buổi trình bày cuối kỳ (hội đồng thực tập FCAJ-AWS).
Nội dung lấy từ docs/defense/chatbot.md trên developer (PR #121). Mỗi slide ghi nguồn ở dòng cuối.
Không đưa Account ID, ARN, ID token, tên bảng thật, domain hay email vào slide.
Xuất PDF: npx @marp-team/marp-cli docs/defense/slides-chatbot.md --pdf
-->

# Luồng `POST /chat`

```text
 Web (ChatPanel) ── câu hỏi + ID token
   ▼
 API Gateway ── Cognito authorizer
   ▼
 Lambda chat-api ── đếm lượt (20/người, 100/ngày toàn hệ thống)
   ▼
 Bedrock Converse: Claude Haiku 4.5, prompt chatbot-haiku-v2
   ⇅ get_forecast   ⇅ get_news   (tối đa 3 vòng tool)
   ▼
 answer · forecasts_used · citations · quota · disclaimer
```

- Trả lời một lần, không streaming; `temperature` 0, `max_tokens` 1500
- Hạn chót = mốc 29 giây của API Gateway trừ 4 giây dự phòng, tính cả cold start; không đủ thời gian thì trả `504`
- Hết lượt thì `429`; bảng đếm lượt không lưu câu hỏi hay câu trả lời
- Mọi câu đi Haiku vì router không đạt (slide 3)

<!--
Ghi chú người nói: Chatbot là một Lambda nằm sau cùng API Gateway và Cognito với API dự báo. Số liệu không do model tự nghĩ ra mà lấy qua tool, nên trùng với trang dự báo. Giới hạn lượt và hạn chót 29 giây là để giữ chi phí và không để người dùng chờ vô hạn.
Gợi ý hình: sơ đồ khối như trên, hoặc phần chat trong sơ đồ hiện trạng (#94).
-->

<p class="small">Nguồn: chatbot.md §2, §4, Phụ lục A</p>

---

# Tool, nguồn tin và kiểm link

- **`get_forecast` v2:** chỉ trả q10/q50/q90 theo %, xác suất tăng và độ rộng khoảng 80% tính sẵn; vàng, bạc không trả mức giá. Model không phải tự tính
- **`get_news`:** tin Fed/EIA **gắn nhãn tay** tới khi bảo vệ (ADR-0013): gắn nhãn tự động bằng Nova chỉ đạt direction 52,4%, dưới ngưỡng 80%
- **`citations`:** server chỉ giữ tin do `get_news` trả trong lượt **và** có link xuất hiện trong câu trả lời; web chỉ tạo link từ `citations`
- **Kiểm link lạ (#104, #109):** link trong câu trả lời không thuộc tin của tool được ghi log `citation_link_mismatch`; benchmark tính câu đó là trượt
- Trạng thái: log lên Lambda từ lần deploy `CpawsApi` tối 13/11, **chưa xác nhận**; chỉ ghi log, chưa có alarm

<!--
Ghi chú người nói: Lớp kiểm link có từ một lỗi thật ở buổi tập dượt 7/11: model chép sai một ký tự trong link thông cáo, link hỏng và tin bị loại khỏi trích nguồn. Sau đó nhóm thêm lớp kiểm ở code, dùng chung cho Lambda và benchmark; soát lại 396 câu trả lời cũ không thấy link lạ nào.
Gợi ý hình: một câu trả lời mẫu, khoanh phần trích nguồn (nguồn, ngày, link).
-->

<p class="small">Nguồn: chatbot.md §5.1, §5.2, §6.2; ADR-0013; PR #104, #107, #109</p>

---

# Kết quả đánh giá: ba kết quả âm có kiểm soát

| Lần đo | Kết quả | Ngưỡng | Quyết định |
|---|---:|---:|---|
| Benchmark v2 (30/10), prompt v2 | 14/30 | ≥ 25 | Chưa đạt, vẫn là bản trên `/chat` |
| Router theo luật, bộ giữ riêng (04/11) | 26/30 (86,7%) | ≥ 90% | Không đưa vào `/chat` |
| Prompt v4 chính thức (11/11), bộ B | 17/30 | ≥ 25 | Không đạt |
| Prompt v4 chính thức (11/11), bộ A | 5/8 | ≥ 7 | Không đạt |

- Vi phạm chính sách (chấm tay): **0** ở cả v2 và v4; làm theo injection trong tin: 0
- Router sai 4 câu, đều là câu đơn giản bị đưa sang Haiku: chỉ tốn thêm chi phí, không câu nào mất số liệu
- v4 trượt chủ yếu vì tự gắn nhãn nghiêng tăng/giảm và thiếu phần bắt buộc

<!--
Ghi chú người nói: Cả ba lần đo đều không đạt ngưỡng, và nhóm trình bày đúng như vậy. Điểm giữ được qua mọi lần đo là chatbot không tư vấn đầu tư và không làm theo chỉ dẫn lồng trong tin. Bộ câu v4 do Long soạn mà không đọc prompt, nên đây là phép đo độc lập.
Gợi ý hình: bảng trên, hoặc biểu đồ cột "câu đạt / ngưỡng" cho 4 dòng.
-->

<p class="small">Nguồn: chatbot.md §3.2, §7.2, §7.4; PR #66, #100, #120</p>

---

# Vì sao giữ v2, giới hạn và hướng tiếp theo

**Vì sao giữ v2**
- Ngưỡng chốt trước, khóa SHA-256 bộ câu, prompt, fixture và code tool, chạy chính thức đúng một lần
- Không sửa prompt rồi chạy lại trên bộ đã xem; v4 không đạt nên `/chat` giữ `chatbot-haiku-v2`

**Giới hạn**
- Lỗi diễn giải số và Markdown `**` của v2 vẫn còn trên `/chat`
- Benchmark chạy trên fixture, một lượt, chưa đo hội thoại nhiều lượt
- Guardrails còn `DRAFT`, **chưa bật**; không bật sau benchmark vì sẽ đổi hành vi bản đã đo

**Hướng sau dự án:** bộ câu mới cho prompt kế tiếp, bật Guardrails rồi đo lại, alarm cho log link lạ

<!--
Ghi chú người nói: Giữ v2 không phải vì v2 tốt hơn v4 trên mọi câu, mà vì quy trình đã chốt: chỉ đổi prompt khi bản mới đạt ngưỡng trên bộ chưa xem. Nếu sửa prompt sau khi xem kết quả rồi chạy lại, con số sẽ lạc quan và không còn là phép đo. Chi phí hiện khoảng 0,012 USD mỗi câu theo ước tính benchmark, chưa đối chiếu hóa đơn.
Gợi ý hình: dòng thời gian v1 → v2 → v3 dev → v4 dev → v4 chính thức (Phụ lục C).
-->

<p class="small">Nguồn: chatbot.md §7.1, §7.4, §7.5, §8; Phụ lục C</p>
