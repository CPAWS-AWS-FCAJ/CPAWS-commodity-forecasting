"""Dòng nguồn trên web phải khớp `SOURCE_ATTRIBUTION` của pipeline dữ liệu (ADR-0005)."""

from __future__ import annotations

from pathlib import Path

from src.data.config import SOURCE_ATTRIBUTION

WEB_SOURCE = Path(__file__).resolve().parents[1] / "web" / "src" / "lib" / "source.ts"


def test_web_source_attribution_matches_data_config() -> None:
    text = WEB_SOURCE.read_text(encoding="utf-8")
    assert f'export const SOURCE_ATTRIBUTION = "{SOURCE_ATTRIBUTION}";' in text
