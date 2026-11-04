"""Dependency-light response projection for the Accuracy API.

Keep the public response shape aligned with src.eval.rolling_accuracy.response_payload.
This module deliberately avoids importing the evaluation stack (NumPy/Pandas).
"""

from __future__ import annotations

DISCLAIMER = "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."
METRICS = ("coverage_80", "width_80", "sign_accuracy", "up_rate")
DISPLAY_METRICS = (*METRICS, "width_80_pct")
HORIZONS = tuple(range(1, 8))
MIN_DISPLAY_BASE_DATES = 20


def _empty_metric(name: str) -> dict:
    """Match src.eval.rolling_accuracy.summarize([]) for one metric."""
    result = {
        "value": None,
        "n_obs": 0,
        "status": "undefined",
        "undefined_reason": "no_evaluable_obs",
    }
    if name == "coverage_80":
        result.update(covered_count=0, n_base_dates=0)
    if name.startswith("width"):
        result["unit"] = "percent" if name.endswith("pct") else "log_return"
    return result


def empty_group() -> dict:
    """Return the exact empty metric group used by summarize([])."""
    return {name: _empty_metric(name) for name in DISPLAY_METRICS}


def _project_group(group: dict, *, overall: bool, ready: bool, enough: bool) -> dict:
    output = {}

    for metric in DISPLAY_METRICS:
        if metric not in group:
            raise ValueError(f"missing metric: {metric}")

        item = {
            key: value
            for key, value in group[metric].items()
            if key != "undefined_reason"
        }

        if overall:
            if not ready:
                display_status = "not_ready"
            elif not enough:
                display_status = "insufficient_data"
            elif item["status"] == "ok":
                display_status = "ready"
            else:
                display_status = "undefined"
        else:
            display_status = "counts_only"

        item["display_status"] = display_status
        item["display_value"] = (
            round(item["value"], 6) if display_status == "ready" else None
        )

        if metric == "coverage_80":
            item.pop("value", None)
            if overall:
                item["min_display_base_dates"] = MIN_DISPLAY_BASE_DATES
        elif item["value"] is not None:
            item["value"] = round(item["value"], 6)

        output[metric] = item

    return output


def build_response(
    *,
    asset: str,
    model_version: str,
    meta: dict | None,
    overall: dict,
    by_horizon: list[dict],
    derived_metrics: dict,
) -> dict:
    """Build the public response after the caller has verified stored evidence."""
    ready = meta is not None

    if not ready:
        state = "not_ready"
        run_id = None
        evaluated_at = None
        window = {
            "basis": "base_date",
            "days": 56,
            "window_start": None,
            "window_end": None,
            "target_cutoff_date": None,
            "first_eligible_base_date": None,
        }
        evidence = {
            "schedule_basis": "trading_calendar_and_predict_schedule",
            "schedule_evidence_status": "not_audited_mvp",
            "issuance_evidence_status": "no_completed_run",
            "expected_count": None,
            "published_count": None,
            "missing_count": None,
        }
        overall = empty_group()
        by_horizon = [
            {"h": horizon, **empty_group()} for horizon in HORIZONS
        ]
        derived_metrics = {
            "width_80_pct": {
                "overall": overall["width_80_pct"],
                "by_horizon": [
                    {"h": horizon, **empty_group()["width_80_pct"]}
                    for horizon in HORIZONS
                ],
            }
        }
    else:
        n_base_dates = overall["coverage_80"]["n_base_dates"]
        enough = n_base_dates >= MIN_DISPLAY_BASE_DATES
        state = "ready" if enough else "collecting"
        run_id = meta["run_id"]
        evaluated_at = meta["evaluated_at"]
        window = meta["window"]
        evidence = meta["evaluation_evidence"]

    if not ready:
        enough = False

    overall_group = dict(overall)
    overall_group["width_80_pct"] = derived_metrics["width_80_pct"]["overall"]

    horizon_derived = {
        item["h"]: item
        for item in derived_metrics["width_80_pct"]["by_horizon"]
    }
    projected_horizons = []

    for horizon in by_horizon:
        h = horizon["h"]
        group = dict(horizon)
        group["width_80_pct"] = horizon_derived[h]
        projected_horizons.append(
            {
                "h": h,
                **_project_group(
                    group,
                    overall=False,
                    ready=ready,
                    enough=enough,
                ),
            }
        )

    return {
        "asset": asset,
        "model_version": model_version,
        "evaluation_kind": "rolling_8w",
        "sample": "all",
        "run_id": run_id,
        "evaluated_at": evaluated_at,
        "window": window,
        "evaluation_evidence": evidence,
        "overall": _project_group(
            overall_group,
            overall=True,
            ready=ready,
            enough=enough,
        ),
        "by_horizon": projected_horizons,
        "data_status": state,
        "disclaimer": DISCLAIMER,
    }
