# SETUP — Chuẩn bị môi trường cho nhóm CPAWS

Làm theo thứ tự. Người phụ trách gợi ý trong ngoặc.

## 1. Công cụ trên máy mỗi người

| Công cụ | Phiên bản | Ghi chú |
|---|---|---|
| Python | 3.11 | venv riêng cho repo |
| Git | mới nhất | cấu hình `user.name`, `user.email` |
| Node.js | 20 LTS trở lên | cần cho AWS CDK |
| AWS CLI | v2 | đăng nhập bằng SSO, không dùng access key dài hạn |
| AWS CDK | v2 (`npm install -g aws-cdk`) | hạ tầng dạng code |
| draw.io Desktop (hoặc app.diagrams.net) | — | sửa `docs/architecture/*.drawio` |
| Node.js + npm | 20 LTS trở lên | cũng dùng cho web (`web/`) |

## 2. Repo (Tiến)

```bash
git init && git add . && git commit -m "chore: cpaws starter"
git remote add origin <url> && git push -u origin main

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip                 # pip cũ trên Windows có thể lỗi khi đọc requirements
pip install -r requirements-dev.txt                 # requirements.txt chỉ có thư viện runtime (phiên bản đã cố định)
pre-commit install && pre-commit autoupdate
python -m pytest -q                                 # 15 test phải xanh
cp .env.example .env                                # điền key thật, KHÔNG commit
```

Bật branch protection cho `main`: 1 review, test xanh.

## 3. AWS (Tuấn + Tiến)

1. **Tài khoản và credit**: hỏi mentor tài khoản nhận credit; tài khoản đang ở Free plan có cần chuyển Paid plan để dùng Bedrock, SageMaker AI không.
2. **Root**: bật MFA, không dùng root hằng ngày.
3. **IAM Identity Center**: mỗi người một user; `AdministratorAccess` cho Tiến và Tuấn, `PowerUserAccess` cho các bạn còn lại. Trên máy: `aws configure sso` → profile `cpaws-dev`.
4. **Budgets**: cảnh báo 25, 50, 100, 200, 300 USD (thực tế và dự báo), email cả nhóm. Bật Cost Anomaly Detection. Bật cost allocation tag `Project`, `Owner`, `Env`.
5. **Bedrock ở ap-southeast-1 — kiểm tra ngay tuần 1, ghi ADR-0004**:
   - Gọi thử Nova Lite (inference profile) và Claude Haiku 4.5 (`global.anthropic.claude-haiku-4-5-…`).
   - Thử tạo một Guardrail và một Knowledge Base (S3 Vectors + Cohere Embed Multilingual v3). Tài liệu Bedrock ghi Singapore "gated" cho hai tính năng này; nếu bị chặn → dùng region dự phòng cho riêng phần Bedrock.
6. **CDK bootstrap**: `cdk bootstrap aws://<account-id>/ap-southeast-1 --profile cpaws-dev`.
7. **API key** (EIA, FRED, Guardian, NYT, API giá kim loại): Secrets Manager; bản dev trong `.env`.

## 4. Checklist tuần 1

- [ ] Repo, branch protection, pre-commit, test xanh trên máy mọi người
- [ ] Tài khoản AWS chung, MFA root, SSO, Budgets + Cost Anomaly Detection
- [ ] Kiểm tra Bedrock ở Singapore (model, Guardrails, Knowledge Bases), ghi ADR-0004
- [ ] Chốt nguồn dữ liệu và điều khoản (EIA, FRED, GPR, Guardian, NYT, API kim loại), ghi ADR-0003
- [ ] Tải lịch sử: giá và tỷ giá từ 2012, tín hiệu và tin tức từ 2014
