"""Behavioral AWS fakes and synthetic prices only; no credentials or network."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import threading

import numpy as np
import pandas as pd
from botocore.exceptions import ClientError

from src.data import calendars
from src.data.config import ASSETS
from src.eval.rolling_accuracy import ASSET_NAMES, Config, baseline_at, price_frame
from src.eval.rolling_sources import Sources
from src.forecast.forecast_record import TARGET_SERIES, target_dates, to_decimal
from src.forecast.returns import QUANTILE_LEVELS, prob_up


def error(code):
    return ClientError({"Error": {"Code": code, "Message": "synthetic"}}, "TestOperation")


def matches(expr, item):
    e = expr.get_expression()
    op, vals = e["operator"], e["values"]
    if op == "AND":
        return all(matches(v, item) for v in vals)
    actual = item.get(vals[0].name)
    if op == "=":
        return actual == vals[1]
    if op == "BETWEEN":
        return vals[1] <= actual <= vals[2]
    raise AssertionError(op)


class Table:
    def __init__(self, records=None, page_size=11):
        self.items = {}
        self.records = records
        self.page_size = page_size
        self.lock = threading.RLock()
        self.fail_metric = None
        self.fail_promote = False
        self.metric_attempts = 0
        self.calls = []

    def get_item(self, Key, ConsistentRead):
        assert ConsistentRead
        with self.lock:
            value = self.items.get((Key["PK"], Key["SK"]))
            return {"Item": copy.deepcopy(value)} if value else {}

    def put_item(self, Item, ConditionExpression):
        assert ConditionExpression == "attribute_not_exists(PK)"
        with self.lock:
            self.calls.append("put")
            if Item["SK"].startswith("METRIC#"):
                self.metric_attempts += 1
                if self.fail_metric == self.metric_attempts:
                    raise RuntimeError("synthetic crash")
            key = Item["PK"], Item["SK"]
            if key in self.items:
                raise error("ConditionalCheckFailedException")
            self.items[key] = copy.deepcopy(Item)
            return {}

    def update_item(
        self,
        Key,
        UpdateExpression,
        ConditionExpression,
        ExpressionAttributeValues,
        ExpressionAttributeNames=None,
    ):
        with self.lock:
            self.calls.append("update")
            key = Key["PK"], Key["SK"]
            old = self.items.get(key, dict(Key))
            v = ExpressionAttributeValues
            if Key["SK"] == "STATE":
                if self.fail_promote:
                    self.fail_promote = False
                    raise RuntimeError("crash after completed")
                allowed = (
                    "latest_run_order" not in old
                    or old["latest_run_order"] < v[":order"]
                    or (old["latest_run_order"] == v[":order"] and old["latest_run_pk"] == v[":pk"])
                )
                if not allowed:
                    raise error("ConditionalCheckFailedException")
                old.update(
                    latest_run_pk=v[":pk"], latest_run_id=v[":id"], latest_run_order=v[":order"]
                )
            else:
                if old.get("status") != v[":previous"] or old.get("payload_hash") != v[":hash"]:
                    raise error("ConditionalCheckFailedException")
                old["status"] = v[":target"]
            self.items[key] = old
            return {}

    def query(self, KeyConditionExpression, ConsistentRead, ExclusiveStartKey=None):
        assert ConsistentRead
        with self.lock:
            self.calls.append("query")
            data = self.records if self.records is not None else list(self.items.values())
            rows = [copy.deepcopy(x) for x in data if matches(KeyConditionExpression, x)]
            rows.sort(key=lambda x: str(x.get("SK", x.get("base_date"))))
            start = (ExclusiveStartKey or {}).get("offset", 0)
            page = {"Items": rows[start : start + self.page_size]}
            if start + self.page_size < len(rows):
                page["LastEvaluatedKey"] = {"offset": start + self.page_size}
            return page


class S3:
    def __init__(self):
        self.objects = {}
        self.denied = set()
        self.list_denied = False
        self.puts = 0

    def seed(self, key, raw, modified):
        self.objects[key] = {
            "raw": raw,
            "ETag": hashlib.md5(raw).hexdigest(),
            "VersionId": hashlib.sha256(raw).hexdigest()[:12],
            "LastModified": pd.Timestamp(modified),
        }

    def get_object(self, Bucket, Key):
        if Key in self.denied:
            raise error("AccessDenied")
        if Key not in self.objects:
            raise error("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key]["raw"]), **self.head_object(Bucket, Key)}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise error("NoSuchKey")
        return {k: v for k, v in self.objects[Key].items() if k != "raw"}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys):
        if self.list_denied:
            raise error("AccessDenied")
        return {
            "Contents": [{"Key": k} for k in sorted(self.objects) if k.startswith(Prefix)][:MaxKeys]
        }

    def put_object(self, Bucket, Key, Body, IfNoneMatch, **kwargs):
        assert IfNoneMatch == "*"
        if Key in self.objects:
            raise error("PreconditionFailed")
        self.puts += 1
        self.seed(Key, Body, "2026-12-20T14:00:00Z")


class Dynamo:
    def __init__(self, forecasts, accuracy):
        self.tables = {"forecasts": forecasts, "accuracy": accuracy}

    def Table(self, name):
        return self.tables[name]


def case(asset="gold", job_date="2026-11-07", first="2026-11-02"):
    cfg = Config(asset, "baseline-q252", "2026-10-26", job_date, job_date + "T13:45:00Z")
    cal = calendars.sessions(ASSETS[asset].calendar, "2025-01-02", job_date)
    dates = cal[cal < pd.Timestamp(job_date)]
    vals = 100 * np.exp(0.002 * np.arange(len(dates)) + 0.013 * np.sin(np.arange(len(dates)) * 1.3))
    prices = pd.DataFrame(
        {
            "asset": asset,
            "date": dates,
            "price": vals,
            "source": ASSETS[asset].primary.source,
            "published_at": (dates + pd.Timedelta(days=1, hours=12)).tz_localize("UTC"),
        }
    )
    rejected = pd.DataFrame(columns=["asset", "date"])
    s3 = S3()

    def seed_snapshot(dt):
        sub = prices.loc[prices.date < pd.Timestamp(dt)]
        for name, frame in [("prices.parquet", sub), ("rejected.parquet", rejected)]:
            buf = io.BytesIO()
            frame.to_parquet(buf, index=False)
            s3.seed(f"clean/prices/dt={dt}/{name}", buf.getvalue(), dt + "T12:02:00Z")
        s3.seed(
            f"clean/prices/dt={dt}/quality.json",
            json.dumps({"assets": {asset: {}}, "stale_sources": {}}).encode(),
            dt + "T12:05:00Z",
        )

    records = []
    frame = price_frame(prices, rejected, asset)
    for base in dates[dates >= pd.Timestamp(first)]:
        dt = (base + pd.Timedelta(days=1)).date().isoformat()
        if dt > job_date:
            continue
        seed_snapshot(dt)
        base = base.date().isoformat()
        hs = []
        for h, target in enumerate(target_dates(asset, base), 1):
            q = [float(to_decimal(x)) for x in baseline_at(frame, base, h)]
            hs.append(
                {"h": h, "target_date": target, "q": q, "prob_up": float(to_decimal(prob_up(q)))}
            )
        records.append(
            {
                "asset": asset,
                "base_date": base,
                "model_version": "baseline-q252",
                "target_series": TARGET_SERIES[asset],
                "is_sample": False,
                "created_at": dt + "T12:15:00Z",
                "input_snapshot_dt": dt,
                "quantile_levels": list(QUANTILE_LEVELS),
                "horizons": hs,
            }
        )
    seed_snapshot(job_date)
    forecasts = Table(records, page_size=2)
    evidence = {
        "release": {
            "approved": True,
            "approved_by": "synthetic-test-reviewer",
            "approved_at": "2026-10-30T13:00:00Z",
            "reference": "synthetic-release",
            "cutover_at": "2026-10-30T12:00:00Z",
            "conditional_write": True,
            "input_asof_checked": True,
        }
    }
    return cfg, Sources(s3, "synthetic-bucket", forecasts), evidence, records


def env():
    return {
        "MODEL_VERSIONS": json.dumps(dict.fromkeys(ASSET_NAMES, "baseline-q252")),
        "CHAMPION_EFFECTIVE_BASE_DATES": json.dumps(dict.fromkeys(ASSET_NAMES, "2026-10-26")),
        "LAKE_BUCKET": "synthetic-bucket",
        "FORECASTS_TABLE": "forecasts",
        "ACCURACY_TABLE": "accuracy",
    }
