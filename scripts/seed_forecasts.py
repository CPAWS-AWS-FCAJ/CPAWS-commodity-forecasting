"""Seed or delete synthetic sample forecasts in DynamoDB."""

import argparse
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

import boto3
import pandas_market_calendars as mcal
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

ASSETS = {
    "gold": {
        "target_series": "GLD",
        "last_price": 2655.40,
        "price_unit": "USD/oz",
        "roll_in_horizon": False,
        "median_step": 0.0005,
        "spread": 0.012,
        "calendar": "NYSE",
    },
    "silver": {
        "target_series": "SLV",
        "last_price": 31.20,
        "price_unit": "USD/oz",
        "roll_in_horizon": False,
        "median_step": 0.0007,
        "spread": 0.020,
        "calendar": "NYSE",
    },
    "brent": {
        "target_series": "BZ=F",
        "last_price": 74.50,
        "price_unit": "USD/bbl",
        "roll_in_horizon": False,
        "median_step": 0.0003,
        "spread": 0.025,
        "calendar": "ICE",
    },
    "wti": {
        "target_series": "CL=F",
        "last_price": 71.32,
        "price_unit": "USD/bbl",
        "roll_in_horizon": False,
        "median_step": 0.0002,
        "spread": 0.028,
        "calendar": "CMEGlobex_CL",
    },
}

QUANTILE_LEVELS = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]

SAMPLE_BASE_DATE = date(2026, 10, 16)
SAMPLE_FX_USD_VND = 26310
SAMPLE_FX_DATE = "2026-10-16"


def rounded(value):
    """Round numeric values to six decimal places."""
    return Decimal(str(value)).quantize(
        Decimal("0.000001"),
        rounding=ROUND_HALF_UP,
    )


def next_trading_days(base_date, count, calendar_name):
    """Return the next trading-session dates."""
    calendar = mcal.get_calendar(calendar_name)
    schedule = calendar.schedule(
        start_date=base_date.isoformat(),
        end_date=date.fromordinal(base_date.toordinal() + 45).isoformat(),
    )

    dates = [
        session_date.date() for session_date in schedule.index if session_date.date() > base_date
    ]

    if len(dates) < count:
        raise ValueError(f"Not enough trading sessions for {calendar_name} after {base_date}.")

    return [day.isoformat() for day in dates[:count]]


def probability_up(quantiles):
    """Interpolate P(return > 0) from sorted quantiles."""
    if len(quantiles) != len(QUANTILE_LEVELS):
        raise ValueError("Expected exactly seven quantiles.")

    if any(quantiles[i] > quantiles[i + 1] for i in range(len(quantiles) - 1)):
        raise ValueError("Quantiles must be nondecreasing.")

    if quantiles[0] >= 0:
        return rounded(Decimal("0.95"))

    if quantiles[-1] <= 0:
        return rounded(Decimal("0.05"))

    for i in range(len(quantiles) - 1):
        lower = quantiles[i]
        upper = quantiles[i + 1]

        if lower <= 0 <= upper:
            q_lower = Decimal(str(QUANTILE_LEVELS[i]))
            q_upper = Decimal(str(QUANTILE_LEVELS[i + 1]))

            if lower == 0 and upper == 0:
                cdf_zero = (q_lower + q_upper) / Decimal(2)
            elif lower == 0:
                cdf_zero = q_lower
            elif upper == 0:
                cdf_zero = q_upper
            else:
                fraction = (Decimal(0) - lower) / (upper - lower)
                cdf_zero = q_lower + fraction * (q_upper - q_lower)

            probability = Decimal(1) - cdf_zero
            return rounded(
                max(
                    Decimal("0.05"),
                    min(Decimal("0.95"), probability),
                )
            )

    raise ValueError("Could not interpolate probability.")


def make_record(asset, config, created_at):
    """Create one synthetic forecast record."""
    target_dates = next_trading_days(SAMPLE_BASE_DATE, 7, config["calendar"])
    horizons = []

    for h, target_date in enumerate(target_dates, start=1):
        median = config["median_step"] * h
        spread = config["spread"]

        values = [
            median - spread,
            median - spread * 0.75,
            median - spread * 0.35,
            median,
            median + spread * 0.35,
            median + spread * 0.75,
            median + spread,
        ]
        quantiles = [rounded(value) for value in values]

        horizons.append(
            {
                "h": h,
                "target_date": target_date,
                "q": quantiles,
                "prob_up": probability_up(quantiles),
            }
        )

    record = {
        "asset": asset,
        "base_date": SAMPLE_BASE_DATE.isoformat(),
        "created_at": created_at,
        "model_version": "sample",
        "target_series": config["target_series"],
        "last_price": rounded(config["last_price"]),
        "price_unit": config["price_unit"],
        "quantile_levels": [Decimal(str(value)) for value in QUANTILE_LEVELS],
        "horizons": horizons,
        "fx_usd_vnd": Decimal(str(SAMPLE_FX_USD_VND)),
        "fx_date": SAMPLE_FX_DATE,
        "stale_sources": [],
        "roll_in_horizon": config["roll_in_horizon"],
        "is_sample": True,
    }

    validate_record(record)
    return record


def validate_record(record):
    """Validate required fields and horizon structure."""
    required = {
        "asset",
        "base_date",
        "created_at",
        "model_version",
        "target_series",
        "last_price",
        "price_unit",
        "quantile_levels",
        "horizons",
        "fx_usd_vnd",
        "fx_date",
        "stale_sources",
        "roll_in_horizon",
        "is_sample",
    }

    missing = required - record.keys()
    if missing:
        raise ValueError(f"Missing fields: {sorted(missing)}")

    if record["model_version"] != "sample" or record["is_sample"] is not True:
        raise ValueError("Sample records must be marked as sample.")

    if len(record["horizons"]) != 7:
        raise ValueError("Each record must contain seven horizons.")

    if len(record["quantile_levels"]) != 7:
        raise ValueError("Expected seven quantile levels.")

    previous_date = record["base_date"]

    for expected_h, horizon in enumerate(record["horizons"], start=1):
        if horizon["h"] != expected_h:
            raise ValueError("Horizon numbers must be 1 through 7.")

        if horizon["target_date"] <= previous_date:
            raise ValueError("Target dates must increase after base_date.")

        if len(horizon["q"]) != 7:
            raise ValueError("Each horizon must contain seven quantiles.")

        if any(horizon["q"][i] > horizon["q"][i + 1] for i in range(6)):
            raise ValueError("Quantiles must be nondecreasing.")

        previous_date = horizon["target_date"]


def get_table(args):
    """Create a DynamoDB table resource."""
    session_args = {"region_name": args.region}
    if args.profile:
        session_args["profile_name"] = args.profile

    session = boto3.Session(**session_args)
    return session.resource("dynamodb").Table(args.table)


def sample_key(asset):
    return {
        "asset": asset,
        "base_date": SAMPLE_BASE_DATE.isoformat(),
    }


def delete_samples(table, dry_run=False):
    """Delete only the four expected sample records."""
    records = {}

    # Preflight every key before deleting anything.
    for asset in ASSETS:
        item = table.get_item(
            Key=sample_key(asset),
            ConsistentRead=True,
        ).get("Item")

        if item is None:
            raise SystemExit(
                f"ABORTED: sample record missing for {asset}. No records were deleted."
            )

        if item.get("model_version") != "sample" or item.get("is_sample") is not True:
            raise SystemExit(
                f"ABORTED: {asset} record is not identified as a sample. No records were deleted."
            )

        records[asset] = item

    print(f"Verified {len(records)} sample records for deletion.")
    for asset in records:
        print(f"{asset}: {SAMPLE_BASE_DATE.isoformat()}")

    if dry_run:
        print("Dry run only. No DynamoDB deletes were performed.")
        return

    deleted = 0
    try:
        for asset in records:
            table.delete_item(
                Key=sample_key(asset),
                ConditionExpression=(
                    Attr("is_sample").eq(True) & Attr("model_version").eq("sample")
                ),
            )
            deleted += 1
    except ClientError as exc:
        raise SystemExit(
            f"Delete stopped after {deleted} record(s): {exc}. Inspect DynamoDB before retrying."
        )

    print(f"Successfully deleted {deleted} sample records.")


def seed_samples(table, records, dry_run=False):
    """Write sample records without overwriting existing keys."""
    # Check all keys before writing any records.
    for record in records:
        existing = table.get_item(
            Key={
                "asset": record["asset"],
                "base_date": record["base_date"],
            },
            ConsistentRead=True,
        ).get("Item")

        if existing:
            raise SystemExit(
                "ABORTED: record already exists for "
                f"{record['asset']} / {record['base_date']}. "
                "No records were written."
            )

    if dry_run:
        print("Dry run only. No DynamoDB writes were performed.")
        return

    written = 0
    try:
        for record in records:
            table.put_item(
                Item=record,
                ConditionExpression=(
                    "attribute_not_exists(asset) AND attribute_not_exists(base_date)"
                ),
            )
            written += 1
    except ClientError as exc:
        raise SystemExit(
            f"Write stopped after {written} record(s): {exc}. Inspect DynamoDB before retrying."
        )

    print(f"Successfully wrote {written} records.")


def main():
    parser = argparse.ArgumentParser(description="Seed or delete sample forecasts in DynamoDB.")
    parser.add_argument(
        "--table",
        default="cpaws-dev-forecasts",
        help="DynamoDB table name.",
    )
    parser.add_argument(
        "--region",
        default="ap-southeast-1",
        help="AWS region.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="AWS CLI profile.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate or preview without writing/deleting.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete the four sample records for the configured sample date.",
    )
    args = parser.parse_args()

    if args.delete:
        if args.dry_run:
            # A dry-run delete preview needs no AWS connection.
            print("Delete preview:")
            for asset in ASSETS:
                print(f"{asset}: {SAMPLE_BASE_DATE.isoformat()}")
            print("Dry run only. No DynamoDB deletes were performed.")
            return

        delete_samples(get_table(args))
        return

    created_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    records = [make_record(asset, config, created_at) for asset, config in ASSETS.items()]

    print(f"Validated {len(records)} sample records.")
    for record in records:
        print(
            f"{record['asset']}: "
            f"base_date={record['base_date']}, "
            f"horizons={len(record['horizons'])}, "
            f"first_target={record['horizons'][0]['target_date']}, "
            f"last_target={record['horizons'][-1]['target_date']}, "
            f"is_sample={record['is_sample']}"
        )

    if args.dry_run:
        print("Dry run only. No DynamoDB writes were performed.")
        return

    seed_samples(get_table(args), records)


if __name__ == "__main__":
    main()
