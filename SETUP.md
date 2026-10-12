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
| Claude Code (tùy chọn) | — | tự đọc `CLAUDE.md` và `.claude/skills/` trong repo |

## 2. Repo (Tiến)

```bash
git init && git add . && git commit -m "chore: cpaws starter"
git remote add origin <url> && git push -u origin main

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt                 # requirements.txt chỉ có thư viện runtime
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

## 4. Claude

### 4.1. Project trên claude.ai (mỗi người tạo riêng, hoặc chia sẻ nếu nhóm có gói Team)

1. Vào **Projects → New Project**, đặt tên "CPAWS".
2. Dán nội dung `docs/claude-project-instructions.md` vào phần **Instructions** của Project.
3. Thêm vào **project knowledge**:
   - `CLAUDE.md`
   - `docs/proposal/Proposal_final.docx`
   - `docs/architecture/CPAWS-architecture-en.png`
   - 9 file `SKILL.md` trong `.claude/skills/`
   - các ADR trong `docs/adr/`
   - file nhiệm vụ của mình trong `docs/team/` (ví dụ `khai-tasks.md`)
4. Nếu có file bổ sung cá nhân (ví dụ `docs/team/khai-project-instructions.md`), dán tiếp vào phần Instructions.

Các chat trong cùng Project không chia sẻ nội dung với nhau, trừ project knowledge — cập nhật knowledge khi có quyết định mới.

### 4.2. Skills trên claude.ai

Có 9 skill. Mỗi skill là một file ZIP chứa thư mục trùng tên skill (sẵn trong `dist/skills/`). Vào **Customize → Skills → + → Create skill → Upload a skill**, tải từng ZIP. Cần bật code execution (gói Free/Pro/Max: Settings → Capabilities; gói Team/Enterprise: owner bật trong Organization settings). Trên gói cá nhân, mỗi người tự upload vào tài khoản của mình.

### 4.3. Claude Code

Mở repo bằng Claude Code: `CLAUDE.md` và các skill trong `.claude/skills/` được nạp tự động.

Commit do người làm: `.claude/settings.json` (chia sẻ cho cả nhóm) chặn Claude chạy `git commit`, `git push`, `git merge`, `git rebase`, `git reset --hard` và đọc `.env`. Claude chỉ sửa file; mỗi người tự xem diff (`git diff`), chỉnh rồi commit. Kiểm tra file đã được nạp bằng lệnh `/status` trong Claude Code.

Cá nhân hóa: `cp CLAUDE.local.md.example CLAUDE.local.md`, sửa tên và đường dẫn file nhiệm vụ của mình. File này đã nằm trong `.gitignore`. Nếu Claude Code không tự đọc file này, mở đầu phiên bằng: "Đọc docs/team/<tên>-tasks.md".

## 5. Checklist tuần 1

- [ ] Repo, branch protection, pre-commit, test xanh trên máy mọi người
- [ ] Tài khoản AWS chung, MFA root, SSO, Budgets + Cost Anomaly Detection
- [ ] Kiểm tra Bedrock ở Singapore (model, Guardrails, Knowledge Bases), ghi ADR-0004
- [ ] Chốt nguồn dữ liệu và điều khoản (EIA, FRED, GPR, Guardian, NYT, API kim loại), ghi ADR-0003
- [ ] Tải lịch sử: giá và tỷ giá từ 2012, tín hiệu và tin tức từ 2014
- [ ] Project Claude có instructions + knowledge; skills đã upload
