"""EIA API v2, giá giao ngay RWTC/RBRTE (chỉ dùng đối chiếu). Phân trang 5.000 dòng/lần.

EIA phát hành giá giao ngay hằng tuần. Key bắt buộc nằm trong query (EIA không đọc header),
nên không bao giờ log URL hay đối tượng request.
"""

from __future__ import annotations

import gzip
import json

import pandas as pd
import requests

from . import FetchResult, SourceError, finalize_bars

API_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
PAGE = 5000


class EIASource:
    name = "eia"

    def __init__(self, api_key: str, session: requests.Session | None = None, timeout: int = 60):
        if not api_key:
            raise SourceError("EIA_API_KEY is empty")
        self.key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch(self, symbol: str, start: str, end: str | None = None) -> FetchResult:
        rows, pages, offset = [], [], 0
        while True:
            params = {
                "api_key": self.key,
                "frequency": "daily",
                "data[0]": "value",
                "facets[series][]": symbol,
                "start": start,
                "sort[0][column]": "period",
                "sort[0][direction]": "asc",
                "offset": offset,
                "length": PAGE,
            }
            if end:
                params["end"] = end
            try:
                r = self.session.get(API_URL, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                raise SourceError(f"eia {symbol}: {type(e).__name__}") from None
            if r.status_code != 200:
                raise SourceError(f"eia {symbol}: HTTP {r.status_code}")
            body = r.json()
            resp = body.get("response", {})
            data = resp.get("data", [])
            pages.append(body)
            rows.extend(data)
            offset += len(data)
            total = int(resp.get("total", offset) or 0)
            if not data or offset >= total:
                break
        vals = [(x["period"], x["value"]) for x in rows if x.get("value") is not None]
        if not vals:
            raise SourceError(f"eia {symbol}: empty response")
        s = pd.Series([float(v) for _, v in vals], index=pd.to_datetime([p for p, _ in vals]))
        s = s[~s.index.duplicated(keep="last")]
        bars = finalize_bars(pd.DataFrame({"close": s}))
        raw = gzip.compress(json.dumps(pages).encode("utf-8"))
        return FetchResult(self.name, symbol, bars, raw, f"{symbol}.json.gz", n_requests=len(pages))
