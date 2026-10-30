"""Router theo luật cho chatbot (ADR-0004 mục 1): chọn nhánh simple (Nova 2 Lite) hay complex
(Claude Haiku 4.5) cho một câu hỏi, không gọi LLM.

Thứ tự luật (luật đầu tiên khớp quyết định):
1. ngoài phạm vi trong ngày → simple; ngoài phạm vi sản phẩm → simple, trừ khi câu còn hỏi về
   tài sản trong phạm vi kèm ý dự báo (câu hỗn hợp) → complex
2. việc không liên quan, không nhắc tài sản → simple
3. tư vấn đầu tư: kèm phân tích dự báo/tin → complex, chỉ xin tư vấn → simple
4. tin tức/lý do kèm tài sản → complex
5. hỏi khái niệm (không có kỳ hạn, không hỏi con số, không hỏi "dự báo" của tài sản) → simple
6. tài sản kèm ý dự báo, kỳ hạn hoặc hỏi con số → complex
7. câu hỏi về chatbot, chào hỏi hoặc chỉ nhắc khái niệm, không có tài sản và kỳ hạn → simple
8. còn lại (không chắc) → complex
Cụm từ nằm trong configs/chatbot_router.py.
"""

from __future__ import annotations

import importlib
import re
import unicodedata
from dataclasses import dataclass

R = importlib.import_module("configs.chatbot_router")

_VI_MARKS = set("àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ")


@dataclass(frozen=True)
class RouteDecision:
    branch: str  # R.SIMPLE hoặc R.COMPLEX
    rule: str  # tên luật đã quyết định, để ghi log và kiểm thử


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"\s+", " ", text).strip()


def fold(text: str) -> str:
    """Bỏ dấu tiếng Việt: "dầu thô" → "dau tho"."""
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


class _Text:
    """Câu đã chuẩn hóa. Câu có dấu so với cụm có dấu; câu gõ không dấu so với cụm đã bỏ dấu
    (nên "dầu" và "đầu" chỉ lẫn nhau khi người dùng gõ không dấu)."""

    def __init__(self, question: str):
        self.raw = _normalize(question)
        self.accented = bool(_VI_MARKS & set(self.raw))
        self.text = self.raw if self.accented else fold(self.raw)

    def _term(self, term: str) -> str:
        return term if self.accented else fold(term)

    def _pattern(self, term: str) -> str:
        return rf"(?<!\w){re.escape(self._term(term))}(?!\w)"

    def has(self, terms) -> bool:
        return any(re.search(self._pattern(t), self.text) for t in terms)

    def matches(self, patterns) -> bool:
        return any(re.search(self._term(p), self.text) for p in patterns)

    def without(self, terms) -> _Text:
        """Bản sao đã xóa các cụm cho trước (cụm dài xóa trước)."""
        out = _Text.__new__(_Text)
        out.raw, out.accented, out.text = self.raw, self.accented, self.text
        for t in sorted(terms, key=len, reverse=True):
            out.text = re.sub(self._pattern(t), " ", out.text)
        return out


def route(question: str) -> RouteDecision:
    """Chọn nhánh cho một câu hỏi tiếng Việt (hoặc tiếng Anh ngắn)."""
    t = _Text(question)
    if not t.text:
        return RouteDecision(R.DEFAULT_BRANCH, "empty")

    rest = t.without(R.OUT_OF_SCOPE_PRODUCT_TERMS)  # bỏ "vàng nhẫn", "dầu diesel"...
    has_asset = rest.has(R.ASSET_TERMS)
    has_time = t.has(R.TIME_TERMS) or t.matches(R.TIME_PATTERNS)
    has_number = t.has(R.NUMBER_REQUEST_TERMS)
    has_forecast = t.has(R.FORECAST_TERMS)

    if t.has(R.OUT_OF_SCOPE_INTRADAY_TERMS):
        return RouteDecision(R.SIMPLE, "out_of_scope_intraday")
    if t.has(R.OUT_OF_SCOPE_PRODUCT_TERMS):
        if has_asset and (has_time or rest.has(R.FORECAST_TERMS)):
            return RouteDecision(R.COMPLEX, "mixed_scope")
        return RouteDecision(R.SIMPLE, "out_of_scope_product")
    if t.has(R.OFF_TOPIC_TERMS) and not has_asset:
        return RouteDecision(R.SIMPLE, "off_topic")
    if t.has(R.ADVICE_TERMS):
        if has_asset and (t.has(R.ANALYSIS_TERMS) or t.has(R.NEWS_TERMS)):
            return RouteDecision(R.COMPLEX, "embedded_advice")
        return RouteDecision(R.SIMPLE, "advice_only")
    if has_asset and t.has(R.NEWS_TERMS):
        return RouteDecision(R.COMPLEX, "news")
    asks_asset_forecast = has_asset and t.has(("dự báo", "forecast"))
    if t.has(R.DEFINITION_TERMS) and not (has_time or has_number or asks_asset_forecast):
        return RouteDecision(R.SIMPLE, "definition")
    if has_asset and (has_forecast or has_time or has_number):
        return RouteDecision(R.COMPLEX, "forecast")
    if not has_asset and not has_time:  # có kỳ hạn thì cần số liệu → không chắc → Haiku
        if t.has(R.META_TERMS):
            return RouteDecision(R.SIMPLE, "meta")
        if t.has(R.GREETING_TERMS) and not (has_forecast or has_time):
            return RouteDecision(R.SIMPLE, "greeting")
        if t.has(R.CONCEPT_TERMS):
            return RouteDecision(R.SIMPLE, "concept")
    return RouteDecision(R.DEFAULT_BRANCH, "default_uncertain")
