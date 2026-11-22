"""NBP (Ngân hàng Quốc gia Ba Lan): giá vàng PLN/g và USD/PLN bảng A, không cần key.

Chỉ dùng trong quality.py để đối chiếu mức giá và trung bình tháng của vàng; NBP chốt giá
khoảng trưa giờ Warsaw nên không dùng đối chiếu return ngày (lệch một ngày với giá Mỹ).
"""

from __future__ import annotations

import gzip
import json
from datetime import timedelta

import pandas as pd
import requests

from ..config import NBP_FIRST_DATE
from . import FetchResult, SourceError, finalize_bars

BASE_URL = "https://api.nbp.pl/api"
MAX_DAYS = 93
OZ_G = 31.1034768


class NBPSource:
    name = "nbp"

    def __init__(self, session: requests.Session | None = None, timeout: int = 60):
        self.session = session or requests.Session()
        self.timeout = timeout

    def _chunks(self, path: str, start: str, end: str) -> tuple[list, int]:
        d0, d_end = pd.Timestamp(start), pd.Timestamp(end)
        bodies, n = [], 0
        while d0 <= d_end:
            d1 = min(d0 + timedelta(days=MAX_DAYS - 1), d_end)
            url = f"{BASE_URL}/{path}/{d0.date()}/{d1.date()}/"
            r = self.session.get(url, headers={"Accept": "application/json"}, timeout=self.timeout)
            n += 1
            if r.status_code == 200:
                bodies.append(r.json())
            elif r.status_code != 404:  # 404 = khoảng không có dữ liệu
                raise SourceError(f"nbp {path}: HTTP {r.status_code}")
            d0 = d1 + timedelta(days=1)
        return bodies, n

    def fetch_gold_usd_oz(self, start: str, end: str) -> FetchResult:
        start = max(pd.Timestamp(start), pd.Timestamp(NBP_FIRST_DATE)).strftime("%Y-%m-%d")
        gold, n1 = self._chunks("cenyzlota", start, end)
        usd, n2 = self._chunks("exchangerates/rates/a/usd", start, end)
        g = {x["data"]: float(x["cena"]) for b in gold for x in b}
        u = {x["effectiveDate"]: float(x["mid"]) for b in usd for x in b["rates"]}
        df = pd.DataFrame({"pln_g": pd.Series(g), "usdpln": pd.Series(u)}).dropna()
        df.index = pd.to_datetime(df.index)
        bars = finalize_bars(pd.DataFrame({"close": df["pln_g"] * OZ_G / df["usdpln"]}))
        raw = gzip.compress(json.dumps({"gold": gold, "usd": usd}).encode("utf-8"))
        return FetchResult(self.name, "gold_usd_oz", bars, raw, "gold_usd_oz.json.gz", n1 + n2)
