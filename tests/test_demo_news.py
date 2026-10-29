"""Bộ tin demo cho `get_news` (infra/lambda/chat_api/news/, dùng qua NEWS_DIR khi demo 8/11/2026).

Kiểm: mỗi tài sản một file đọc được bằng JsonFileNewsRepository, không tin nào bị get_news bỏ,
7 trường đúng schema của contract (docs/api/contract.md, mục "Nguồn dữ liệu của tool get_news"),
nguồn chỉ là trang chính thức Fed/EIA và quy ước gắn nhãn labeling-v3 giữa các tài sản.
Nguồn, nhãn và cách làm mới bộ tin: docs/api/demo-news.md.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

from src.chatbot import news as N

ROOT = Path(__file__).resolve().parents[1]
NEWS_DIR = ROOT / "infra" / "lambda" / "chat_api" / "news"
HANDLER = ROOT / "infra" / "lambda" / "chat_api" / "handler.py"
PUBLISHED_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DIRECTIONS = {"bullish", "bearish", "mixed", "uncertain"}
SOURCES = {"Federal Reserve": "www.federalreserve.gov", "EIA": "www.eia.gov"}


def _load(asset: str) -> dict:
    return json.loads((NEWS_DIR / f"{asset}.json").read_text(encoding="utf-8"))


def _all_items() -> list[tuple[str, dict]]:
    return [(a, it) for a in N.ASSETS for it in _load(a)["items"]]


@pytest.mark.parametrize("asset", N.ASSETS)
def test_file_per_asset(asset):
    data = _load(asset)
    assert data["asset"] == asset
    assert isinstance(data["items"], list) and data["items"]
    # nhiều hơn MAX_ITEMS thì get_news cắt bớt, tin cũ không bao giờ tới được model
    assert len(data["items"]) <= N.MAX_ITEMS


@pytest.mark.parametrize("asset", N.ASSETS)
def test_repository_reads_every_item(asset):
    repo = N.JsonFileNewsRepository(NEWS_DIR)
    got = repo.items(asset, dt.date(2000, 1, 1), dt.date(2100, 1, 1))
    assert len(got) == len(_load(asset)["items"])


@pytest.mark.parametrize("asset", N.ASSETS)
def test_get_news_keeps_every_item(asset, caplog):
    items = _load(asset)["items"]
    days = sorted(it["published_at"][:10] for it in items)
    caplog.set_level(logging.WARNING, logger="cpaws.chatbot.news")
    res = N.get_news(
        {"asset": asset, "from_date": days[0], "to_date": days[-1], "min_impact": 0},
        N.JsonFileNewsRepository(NEWS_DIR),
    )
    assert "error" not in res
    assert len(res["items"]) == len(items)
    assert not [r for r in caplog.records if "skipped" in r.getMessage()]


@pytest.mark.parametrize("asset,item", _all_items())
def test_item_schema(asset, item):
    assert set(item) == set(N.ITEM_FIELDS)
    assert isinstance(item["title"], str) and 0 < len(item["title"]) <= 300
    assert isinstance(item["summary"], str) and 0 < len(item["summary"]) <= 600
    assert PUBLISHED_AT.match(item["published_at"])
    dt.datetime.fromisoformat(item["published_at"])  # ngày giờ có thật (Python 3.11+ nhận "Z")
    score = item["impact_score"]
    assert isinstance(score, int) and not isinstance(score, bool) and 0 <= score <= 3
    assert item["direction"] in DIRECTIONS
    if score == 0:
        assert item["direction"] == "uncertain"  # labeling-v3 mục 6.1


@pytest.mark.parametrize("asset,item", _all_items())
def test_official_source(asset, item):
    url = urlparse(item["link"])
    assert url.scheme == "https"
    assert url.netloc == SOURCES[item["source"]]


@pytest.mark.parametrize("asset,item", _all_items())
def test_cross_asset_convention(asset, item):
    # labeling-v3: tin EIA không có tác động lên vàng/bạc; tin Fed không có tác động lên dầu
    other_side = {"EIA": ("gold", "silver"), "Federal Reserve": ("brent", "wti")}
    if asset in other_side[item["source"]]:
        assert (item["impact_score"], item["direction"]) == (0, "uncertain")


def test_same_article_same_metadata():
    # một bài ở nhiều tài sản thì chỉ khác nhãn, giống cách NewsLabels ghi mỗi tài sản một item
    seen: dict[str, tuple] = {}
    for _, it in _all_items():
        meta = (it["title"], it["summary"], it["source"], it["published_at"])
        assert seen.setdefault(it["link"], meta) == meta
    links = {a: {it["link"] for it in _load(a)["items"]} for a in N.ASSETS}
    assert all(v == links["gold"] for v in links.values())


def test_handler_reads_news_dir(monkeypatch):
    # cách bật khi demo: bỏ NEWS_TABLE_NAME, đặt NEWS_DIR (trên Lambda là /var/task/news)
    spec = importlib.util.spec_from_file_location("chat_handler_demo_news", HANDLER)
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    monkeypatch.delenv("NEWS_TABLE_NAME", raising=False)
    monkeypatch.setenv("NEWS_DIR", str(NEWS_DIR))
    repo = handler.news_repository()
    assert isinstance(repo, N.JsonFileNewsRepository)
    res = N.get_news({"asset": "gold", "to_date": "2026-10-29"}, repo)
    assert [it["link"] for it in res["items"]] == [
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm"
    ]
