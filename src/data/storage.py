"""Lưu trữ cùng layout cho local (data/lake/) và S3 (s3://cpaws-<env>-lake/).

  raw/<source>/dt=YYYY-MM-DD/<file>                 phản hồi gốc
  clean/prices/dt=YYYY-MM-DD/prices.parquet         bản chụp toàn bộ lịch sử (dạng dài)
  clean/prices/dt=YYYY-MM-DD/rejected.parquet       các dòng bị loại kèm flag
  clean/prices/dt=YYYY-MM-DD/quality.json
  clean/reference_prices/dt=YYYY-MM-DD/reference.parquet
  clean/display_factors/dt=YYYY-MM-DD/display_factors.parquet
  clean/display_fx/dt=YYYY-MM-DD/display_fx.parquet  tỷ giá cho hiển thị (có thể pending_confirm)
Ghi đè theo khóa: chạy lại cùng ngày ghi đè đúng các file đó.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pandas as pd

_DT = re.compile(r"dt=(\d{4}-\d{2}-\d{2})")


class LocalStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def write_bytes(self, key: str, data: bytes) -> str:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return str(p)

    def read_bytes(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()

    def list_dirs(self, prefix: str) -> list[str]:
        p = self.root / prefix
        return sorted(x.name for x in p.iterdir() if x.is_dir()) if p.exists() else []


class S3Storage:
    """Bucket do stack CpawsData tạo (không tạo bucket ở đây). root: tiền tố key ("" hoặc "x/")."""

    def __init__(self, bucket: str, client=None, root: str = ""):
        import boto3

        self.bucket = bucket
        self.root = root
        self.s3 = client or boto3.client("s3")

    def _k(self, key: str) -> str:
        return f"{self.root}{key}"

    def write_bytes(self, key: str, data: bytes) -> str:
        self.s3.put_object(Bucket=self.bucket, Key=self._k(key), Body=data)
        return f"s3://{self.bucket}/{self._k(key)}"

    def read_bytes(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.bucket, Key=self._k(key))["Body"].read()

    def exists(self, key: str) -> bool:
        k = self._k(key)
        r = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=k, MaxKeys=1)
        return any(o["Key"] == k for o in r.get("Contents", []))

    def list_dirs(self, prefix: str) -> list[str]:
        pages = self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=self._k(prefix.rstrip("/") + "/"), Delimiter="/"
        )
        return sorted(
            cp["Prefix"].rstrip("/").split("/")[-1]
            for pg in pages
            for cp in pg.get("CommonPrefixes", [])
        )


def write_parquet(st, key: str, df: pd.DataFrame) -> str:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return st.write_bytes(key, buf.getvalue())


def read_parquet(st, key: str) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(st.read_bytes(key)))


def write_json(st, key: str, obj: dict) -> str:
    return st.write_bytes(key, json.dumps(obj, indent=2, ensure_ascii=False, default=str).encode())


def latest_dt(
    st, prefix: str, on_or_before: str | None = None, must_have: str | None = None
) -> str | None:
    """dt mới nhất (<= on_or_before); nếu có must_have thì bỏ qua thư mục thiếu file đó."""
    dts = sorted(
        (m.group(1) for d in st.list_dirs(prefix) if (m := _DT.fullmatch(d))), reverse=True
    )
    for d in dts:
        if on_or_before and d > on_or_before:
            continue
        if must_have and not st.exists(f"{prefix}/dt={d}/{must_have}"):
            continue
        return d
    return None
