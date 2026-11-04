---
marp: true
theme: default
paginate: true
size: 16:9
title: CPAWS chatbot demo 8/11/2026
style: |
  section { font-size: 26px; }
  h1 { font-size: 42px; }
  table { font-size: 22px; }
  pre { font-size: 19px; line-height: 1.35; }
  .small { font-size: 18px; color: #555; }
---

<!--
Slide cho buổi demo chatbot nội bộ team, 8/11/2026.
Nội dung lấy từ docs/demo/demo-chatbot-2026-11-08.md (PR #77), mục 3, 6 và 8.
Không đưa Account ID, ARN, ID token, tên bảng thật hay email vào slide.
Xuất PDF: npx @marp-team/marp-cli docs/demo/slides-demo-chatbot-2026-11-08.md --pdf
-->

# CPAWS: chatbot giải thích dự báo giá hàng hóa

Demo nội bộ team, Chủ nhật 8/11/2026

- Trình bày: Phước. Chạy máy: Tiến, trên web của nhóm

<!-- Chờ Phước chốt nơi chạy web: domain Amplify (Khải đề xuất) hay localhost:5173 (dự phòng). Chốt xong thì ghi vào dòng trên nếu muốn. -->

- `POST /chat` thật trên AWS: Bedrock Claude Haiku 4.5, prompt `chatbot-haiku-v2`
- 15 phút demo, 10 phút hỏi đáp

---

# Chatbot làm gì, không làm gì

**Trong phạm vi**

- Giải thích dự báo của hệ thống cho **vàng, bạc, Brent, WTI**, 1–7 phiên tới, bằng tiếng Việt
- Số liệu **chỉ lấy từ tool** `get_forecast`, khớp với trang dự báo
- Tin Fed/EIA có **trích nguồn** (nguồn, ngày, link). Tin là yếu tố có thể ảnh hưởng; dự báo không dùng tin
- Dự báo có khoảng 80% và xác suất tăng, kèm câu: *"Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."*
- Vàng, bạc dựa trên GLD/SLV: chỉ nêu % và xác suất tăng, không nêu giá

**Ngoài phạm vi**

- Tư vấn mua, bán, giữ: chatbot từ chối
- Xăng dầu bán lẻ Việt Nam, giá vàng trong nước, dự đoán trong ngày, tài sản khác

<!-- Câu ngoài phạm vi chỉ nêu trên slide, không gõ vào chatbot (kịch bản mục 4.1). Khán giả hỏi ngoài kịch bản thì trả lời bằng lời. -->

---

# Luồng `POST /chat`

```text
 Web (ChatPanel)
   │  câu hỏi + ID token
   ▼
 API Gateway ── Cognito authorizer
   │
   ▼
 Lambda chat-api ── kiểm lượt hỏi (20/người, 100/ngày toàn hệ thống)
   │
   ▼
 Bedrock Converse: Claude Haiku 4.5 (prompt chatbot-haiku-v2, đã khóa)
   │   ⇅ get_forecast → bảng dự báo, cùng hàm định dạng với GET /forecasts
   │   ⇅ get_news     → bộ tin Fed/EIA gắn nhãn tay (ADR-0013)
   ▼
 Response: answer · forecasts_used · citations · quota · disclaimer
```

- Trả lời một lần, không streaming; Lambda tự trả `504` trước mốc 29 giây của API Gateway
- `citations` chỉ gồm link của tin do `get_news` trả trong lượt đó
- **Nhãn tin gắn tay tới khi bảo vệ** (ADR-0013): Nova gắn nhãn tự động (labeling-v3) chưa đạt ngưỡng
- Router chưa có: mọi câu đi Haiku + tool

---

# Benchmark bộ v2 (30/10): **chưa đạt**

Bài B = cấu hình chạy trong demo (Haiku, prompt v2, tool v2), chạy trên fixture

| Chỉ số | Bài B |
|---|---|
| Câu đạt (kiểm tự động + rubric) | **14/30** (ngưỡng ≥ 25) |
| Vi phạm chính sách (tư vấn đầu tư, ngoài phạm vi) | 0 |
| Làm theo injection trong tin | 0/3 |
| Gọi đúng tool | 28/30 |
| Số không nguồn / nêu giá vàng, bạc / gắn sai nhãn "khoảng 80%" | 0 / 0 / 0 |
| Thời gian mỗi câu, trung vị / p90 | 4.023 / 5.733 ms |
| Chi phí ước tính 30 câu | 0,368 USD (≈ 0,012 USD/câu) |

- Lỗi chính: diễn giải số sai (bỏ dấu âm, so hai số âm ngược chiều, gọi q90 là "tăng tối đa"), thiếu ý bắt buộc, tự thêm nhận định
- Bộ câu demo cố định để tránh các loại câu đã biết là yếu

<p class="small">Nguồn: docs/experiments/chatbot-benchmark-v2-2026-10.md; results/chatbot-benchmark-2026-10-30-v2/. Bài A (Nova) không áp dụng cho demo.</p>

---

# Việc sau demo

| Việc | Vì sao |
|---|---|
| **Router** chọn Nova hoặc Haiku theo câu hỏi | Hiện mọi câu đi Haiku + tool |
| **Publish Guardrail**, thêm quyền `ApplyGuardrail`, bật lọc prompt attack | Guardrail còn `DRAFT`, `blocked` luôn `false` |
| **Collector ghi `NewsLabels`** | Thay bộ tin JSON đóng trong gói Lambda; nhãn vẫn gắn tay tới khi bảo vệ (ADR-0013) |
| **Bộ câu benchmark v3** | Đo lại các lỗi diễn giải số, thiếu ý của bài B |
| **Streaming** | Đã chọn trả một lần (27/10) để giữ Cognito authorizer và Lambda Python |

Prompt `chatbot-haiku-v2` giữ nguyên tới hết demo; các câu trả lời sai hôm nay được ghi `request_id` để sửa sau.

**Hỏi đáp**
