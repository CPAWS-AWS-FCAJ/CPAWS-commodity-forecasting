"""So link trích nguồn trong câu trả lời với link của tin `get_news` trả về trong lượt.

Một chỗ dùng chung cho Lambda `POST /chat` (`chat.py`: `citations` của response và log
`citation_link_mismatch`) và script đếm của benchmark (`scripts/benchmark/citation_link_report.py`).
Khải review PR #98 và chốt (b) ngày 8/11: chỉ đo và ghi log, không sửa câu trả lời; khi khóa bộ câu
mới cho v4 thì đưa kiểm này vào `check_answer` và thêm file này vào danh sách code được băm.

Module không import gì ngoài thư viện chuẩn.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

CITATION_FIELDS = ("title", "source", "published_at", "link")
# URL http(s) trong câu trả lời. Dừng ở khoảng trắng, ngoặc và dấu nháy (Markdown `[..](url)`,
# "(Nguồn: ..., url)"); dấu câu dính ở cuối URL được bỏ.
_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]+")
_URL_TRAILING = ".,;:!?"


def cited_items(answer_text: str, items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Tin do get_news trả về trong lượt này và có link xuất hiện trong câu trả lời, mỗi link một
    lần (contract `POST /chat`, trường `citations`); không bao giờ lấy link từ chữ model tự viết."""
    seen, out = set(), []
    for it in items:
        link = it.get("link")
        if link and link in answer_text and link not in seen:
            seen.add(link)
            out.append({k: it.get(k) for k in CITATION_FIELDS})
    return out


def stray_links(answer_text: str, items: Iterable[Mapping[str, Any]]) -> list[str]:
    """URL trong câu trả lời không trùng nguyên văn link của tin get_news trả về trong lượt này,
    theo thứ tự xuất hiện, không lặp. Không có tin nào trong lượt thì mọi URL đều lạ."""
    known = {it["link"] for it in items if it.get("link")}
    out: list[str] = []
    for m in _URL_RE.finditer(answer_text or ""):
        url = m.group(0).rstrip(_URL_TRAILING)
        if url not in known and url not in out:
            out.append(url)
    return out


__all__ = ["CITATION_FIELDS", "cited_items", "stray_links"]
